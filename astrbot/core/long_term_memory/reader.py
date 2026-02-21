"""Read pipeline for the Long-Term Memory system.

Retrieves, ranks, filters, and formats memory items for injection
into LLM prompts with strict budget enforcement.
"""

import re
from collections import defaultdict
from datetime import datetime, timezone

from astrbot import logger

from .db import MemoryDB
from .models import MemoryItem
from .policy import MemoryReadPolicy


def _time_decay(updated_at: datetime, half_life_days: float = 30.0) -> float:
    """Compute a time decay score in [0, 1].

    Returns 1.0 for items updated just now, decaying toward 0 over time.
    """
    now = datetime.now(timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    days_since = max(0.0, (now - updated_at).total_seconds() / 86400.0)
    return 1.0 / (1.0 + days_since / half_life_days)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for mixed CJK/English."""
    return max(1, len(text) // 4)


def _lexical_similarity(query_text: str, fact_text: str) -> float:
    """Lightweight lexical similarity in [0, 1] without vector dependencies."""
    query = str(query_text or "").strip().lower()
    fact = str(fact_text or "").strip().lower()
    if not query or not fact:
        return 0.0

    if query in fact or fact in query:
        return 1.0

    # English words + CJK chars for mixed-language matching.
    token_pattern = r"[a-z0-9_]+|[\u4e00-\u9fff]"
    q_tokens = set(re.findall(token_pattern, query))
    f_tokens = set(re.findall(token_pattern, fact))
    if not q_tokens or not f_tokens:
        return 0.0

    overlap = len(q_tokens & f_tokens)
    union = len(q_tokens | f_tokens)
    if union <= 0:
        return 0.0
    return overlap / union


class MemoryReader:
    """Retrieves and formats memory items for prompt injection."""

    def __init__(self, memory_db: MemoryDB) -> None:
        self._db = memory_db

    async def retrieve_memory_context(
        self,
        scope: str,
        scope_id: str,
        read_policy: MemoryReadPolicy,
        query_text: str | None = None,
        additional_scopes: list[tuple[str, str]] | None = None,
    ) -> str:
        """Retrieve memory items and format them for prompt injection.

        Returns a formatted string ready to be prepended to the system prompt,
        or empty string if no relevant memories found or read is disabled.
        """
        if not read_policy.enable:
            return ""

        # Fetch active items for this scope (optionally with fallback scopes)
        scope_targets: list[tuple[str, str]] = [(scope, scope_id)]
        if additional_scopes:
            for extra_scope, extra_scope_id in additional_scopes:
                key = (str(extra_scope).strip(), str(extra_scope_id).strip())
                if key[0] and key[1] and key not in scope_targets:
                    scope_targets.append(key)

        fetch_limit = max(1, read_policy.max_items * 3)
        if len(scope_targets) == 1:
            items = await self._db.get_active_items_for_scope(
                scope=scope,
                scope_id=scope_id,
                min_confidence=read_policy.min_confidence,
                limit=fetch_limit,
            )
        else:
            items = await self._db.get_active_items_for_scopes(
                scopes=scope_targets,
                min_confidence=read_policy.min_confidence,
                limit=fetch_limit * len(scope_targets),
            )

        if not items:
            return ""

        # Remove obvious duplicates across legacy/current scopes.
        items = self._dedupe_items(items)

        # Rank items
        ranked = self._rank_items(items, read_policy, query_text=query_text)

        # Apply diversity filter
        diversified = self._diversity_filter(ranked, read_policy)

        # Apply budget
        selected = self._apply_budget(diversified, read_policy)

        if not selected:
            return ""

        # Format for prompt injection
        return self._format_memory_block(selected)

    def _rank_items(
        self,
        items: list[MemoryItem],
        policy: MemoryReadPolicy,
        query_text: str | None = None,
    ) -> list[tuple[MemoryItem, float]]:
        """Score and rank items by hybrid criteria."""
        scored: list[tuple[MemoryItem, float]] = []

        for item in items:
            recency = _time_decay(item.updated_at)
            importance = item.importance
            similarity = (
                _lexical_similarity(str(query_text), item.fact)
                if query_text
                else item.confidence
            )

            # Without vector similarity (Phase 1), use importance + recency
            # In Phase 2, similarity_weight will use actual cosine similarity
            score = (
                policy.importance_weight * importance
                + policy.recency_weight * recency
                + policy.similarity_weight * similarity
            )
            scored.append((item, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _dedupe_items(self, items: list[MemoryItem]) -> list[MemoryItem]:
        """Dedupe by (type, fact_key), keeping the strongest/newest item."""
        best_by_key: dict[tuple[str, str], MemoryItem] = {}
        for item in items:
            key = (item.type, item.fact_key)
            current = best_by_key.get(key)
            if current is None:
                best_by_key[key] = item
                continue

            # Prefer higher confidence, then newer update time.
            if item.confidence > current.confidence:
                best_by_key[key] = item
            elif item.confidence == current.confidence and item.updated_at > current.updated_at:
                best_by_key[key] = item

        return list(best_by_key.values())

    def _diversity_filter(
        self,
        ranked: list[tuple[MemoryItem, float]],
        policy: MemoryReadPolicy,
    ) -> list[tuple[MemoryItem, float]]:
        """Cap the number of items per type to ensure diversity."""
        type_counts: dict[str, int] = defaultdict(int)
        result: list[tuple[MemoryItem, float]] = []

        for item, score in ranked:
            if type_counts[item.type] >= policy.max_per_type:
                continue
            type_counts[item.type] += 1
            result.append((item, score))

        return result

    def _apply_budget(
        self,
        items: list[tuple[MemoryItem, float]],
        policy: MemoryReadPolicy,
    ) -> list[MemoryItem]:
        """Enforce max_items and max_tokens budget."""
        selected: list[MemoryItem] = []
        total_tokens = 0
        overhead_tokens = _estimate_tokens("[Long-term Memory]\n[End Memory]\n")

        for item, _ in items:
            if len(selected) >= policy.max_items:
                break

            line = self._format_single_item(item)
            line_tokens = _estimate_tokens(line)

            if total_tokens + line_tokens + overhead_tokens > policy.max_tokens:
                continue

            selected.append(item)
            total_tokens += line_tokens

        return selected

    def _format_single_item(self, item: MemoryItem) -> str:
        """Format a single memory item as a bullet line."""
        return f"- [{item.type}] {item.fact} (confidence: {item.confidence:.2f})"

    def _format_memory_block(self, items: list[MemoryItem]) -> str:
        """Format the full memory context block."""
        lines = ["[Long-term Memory]"]
        for item in items:
            lines.append(self._format_single_item(item))
        lines.append("[End Memory]")
        return "\n".join(lines)

"""Memory consolidation for the Long-Term Memory system.

Merges similar memory items within the same scope into more concise,
higher-quality entries using LLM-powered summarization and lightweight
fact_key similarity clustering via difflib.
"""

import json
import re
from collections import defaultdict
from difflib import SequenceMatcher

from astrbot import logger
from astrbot.core.provider.provider import Provider

from .db import MemoryDB
from .models import MemoryItem

# Minimum similarity ratio (0-1) for two fact_keys to be considered
# candidates for the same cluster.
_MIN_KEY_SIMILARITY = 0.55

CONSOLIDATION_PROMPT = """\
You are a memory consolidation assistant. Given a cluster of related memory facts \
about the same user/context, merge them into ONE concise, comprehensive fact.

Rules:
- Preserve all important information; do not lose details.
- If facts conflict, keep the most recent / highest-confidence version.
- Output a single JSON object with keys: "fact", "fact_key", "confidence", "importance".
- The merged fact should be a concise natural-language statement.
- fact_key should be a short, normalized identifier for dedup.

Input facts (JSON array):
{facts_json}

Output ONE merged JSON object only, no other text:"""


def _cluster_by_fact_key(
    items: list[MemoryItem],
    min_similarity: float = _MIN_KEY_SIMILARITY,
) -> list[list[MemoryItem]]:
    """Group items whose fact_keys are similar enough to merge.

    Uses a simple greedy single-linkage approach with SequenceMatcher.
    """
    clusters: list[list[MemoryItem]] = []
    assigned: set[str] = set()

    for i, item_a in enumerate(items):
        if item_a.memory_id in assigned:
            continue
        cluster = [item_a]
        assigned.add(item_a.memory_id)

        for item_b in items[i + 1 :]:
            if item_b.memory_id in assigned:
                continue
            ratio = SequenceMatcher(
                None, item_a.fact_key, item_b.fact_key
            ).ratio()
            if ratio >= min_similarity:
                cluster.append(item_b)
                assigned.add(item_b.memory_id)

        if len(cluster) >= 2:
            clusters.append(cluster)

    return clusters


class MemoryConsolidator:
    """Merges similar memory items using LLM summarization."""

    def __init__(self, memory_db: MemoryDB) -> None:
        self._db = memory_db

    async def run_consolidation(
        self,
        provider: Provider,
        scope: str | None = None,
        scope_id: str | None = None,
        limit: int = 100,
    ) -> int:
        """Consolidate similar memories within scope(s).

        Returns the total number of items that were consolidated (replaced).
        """
        total_consolidated = 0

        if scope and scope_id:
            total_consolidated += await self._consolidate_scope(
                provider, scope, scope_id, limit
            )
        else:
            # Discover all distinct (scope, scope_id) pairs with active items
            scopes = await self._db.list_items(
                status="active", page=1, page_size=1000
            )
            seen: set[tuple[str, str]] = set()
            for item in scopes[0]:
                key = (item.scope, item.scope_id)
                if key not in seen:
                    seen.add(key)
                    total_consolidated += await self._consolidate_scope(
                        provider, item.scope, item.scope_id, limit
                    )

        if total_consolidated > 0:
            logger.info("LTM consolidation: %d items consolidated", total_consolidated)
        return total_consolidated

    async def _consolidate_scope(
        self,
        provider: Provider,
        scope: str,
        scope_id: str,
        limit: int,
    ) -> int:
        """Consolidate within a single scope."""
        items = await self._db.get_active_items_for_scope(
            scope=scope, scope_id=scope_id, limit=limit,
        )
        if len(items) < 2:
            return 0

        # Group by type first, then cluster by fact_key similarity
        by_type: dict[str, list[MemoryItem]] = defaultdict(list)
        for item in items:
            by_type[item.type].append(item)

        consolidated = 0
        for mem_type, type_items in by_type.items():
            clusters = _cluster_by_fact_key(type_items)
            for cluster in clusters:
                try:
                    ok = await self._merge_cluster(
                        provider, scope, scope_id, mem_type, cluster
                    )
                    if ok:
                        consolidated += len(cluster)
                except Exception as e:
                    logger.warning(
                        "LTM consolidation merge failed for cluster: %s", e
                    )

        return consolidated

    async def _merge_cluster(
        self,
        provider: Provider,
        scope: str,
        scope_id: str,
        mem_type: str,
        cluster: list[MemoryItem],
    ) -> bool:
        """Merge a cluster of similar items into one via LLM."""
        facts_for_prompt = [
            {
                "fact": item.fact,
                "fact_key": item.fact_key,
                "confidence": item.confidence,
                "importance": item.importance,
                "evidence_count": item.evidence_count,
            }
            for item in cluster
        ]

        prompt = CONSOLIDATION_PROMPT.format(
            facts_json=json.dumps(facts_for_prompt, ensure_ascii=False)
        )

        try:
            import uuid

            response = await provider.text_chat(
                prompt=prompt,
                session_id=f"ltm_consolidate_{uuid.uuid4().hex[:8]}",
            )
        except Exception as e:
            logger.warning("LTM consolidation LLM call failed: %s", e)
            return False

        if not response or not response.completion_text:
            return False

        raw = response.completion_text.strip()
        # Strip markdown fences
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        json_text = fence.group(1) if fence else raw
        obj_match = re.search(r"\{.*\}", json_text, re.DOTALL)
        if not obj_match:
            return False

        try:
            merged = json.loads(obj_match.group())
        except json.JSONDecodeError:
            return False

        new_fact = merged.get("fact", "")
        new_key = merged.get("fact_key", "")
        if not new_fact or not new_key:
            return False

        # Aggregate evidence and pick best scores
        total_evidence = sum(it.evidence_count for it in cluster)
        max_confidence = max(
            float(merged.get("confidence", 0.5)),
            max(it.confidence for it in cluster),
        )
        max_importance = max(
            float(merged.get("importance", 0.5)),
            max(it.importance for it in cluster),
        )

        # Create the merged item
        from .extractor import _normalize_fact_key

        new_key = _normalize_fact_key(new_key)

        # Check if merged key already exists
        existing = await self._db.get_item_by_fact_key(scope, scope_id, new_key)
        if existing and existing.memory_id not in {it.memory_id for it in cluster}:
            # Key collision with a non-cluster item — update it instead
            await self._db.update_item(
                existing.memory_id,
                fact=new_fact,
                confidence=min(1.0, max_confidence),
                importance=min(1.0, max_importance),
                evidence_count=existing.evidence_count + total_evidence,
            )
        else:
            # Delete old cluster items first (to free the unique constraint)
            for item in cluster:
                await self._db.delete_item(item.memory_id)

            await self._db.insert_item(
                scope=scope,
                scope_id=scope_id,
                type=mem_type,
                fact=new_fact[:500],
                fact_key=new_key,
                confidence=min(1.0, max_confidence),
                importance=min(1.0, max_importance),
                evidence_count=total_evidence,
                status="active",
            )

        # Mark old items as consolidated (if not already deleted)
        if existing and existing.memory_id not in {it.memory_id for it in cluster}:
            for item in cluster:
                await self._db.update_item(item.memory_id, status="consolidated")

        return True

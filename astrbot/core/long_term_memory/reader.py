"""Read pipeline for the Long-Term Memory system.

Retrieves, ranks, filters, and formats memory items for injection
into LLM prompts with strict budget enforcement.
"""

import re
from collections import defaultdict
from datetime import datetime, timezone
from math import sqrt

from astrbot import logger

from .db import MemoryDB
from .models import MemoryItem, MemoryRelation
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
        embedding_provider=None,
        as_of: datetime | None = None,
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
                as_of=as_of,
            )
        else:
            items = await self._db.get_active_items_for_scopes(
                scopes=scope_targets,
                min_confidence=read_policy.min_confidence,
                limit=fetch_limit * len(scope_targets),
                as_of=as_of,
            )

        if not items:
            if not read_policy.include_relations:
                return ""

        # Remove obvious duplicates across legacy/current scopes.
        items = self._dedupe_items(items)
        quantization_mode = self._normalize_vector_quantization_mode(
            getattr(read_policy, "vector_quantization", "none")
        )

        strategy = str(getattr(read_policy, "strategy", "balanced") or "balanced").strip().lower()
        prefetch_relations = read_policy.include_relations or strategy == "relation_first"
        relation_ranked: list[tuple[MemoryRelation, float]] = []
        if prefetch_relations:
            relation_ranked = await self._retrieve_relations(
                scope_targets=scope_targets,
                policy=read_policy,
                query_text=query_text,
                embedding_provider=embedding_provider,
                quantization_mode=quantization_mode,
                as_of=as_of,
            )
        relation_subject_scores = self._build_relation_subject_scores(relation_ranked)

        vector_similarity: dict[str, float] = {}
        if query_text:
            vector_similarity = await self._compute_vector_similarity(
                query_text=query_text,
                items=items,
                embedding_provider=embedding_provider,
                quantization_mode=quantization_mode,
            )

        # Rank items
        ranked = self._rank_items(
            items,
            read_policy,
            query_text=query_text,
            vector_similarity=vector_similarity,
            relation_subject_scores=relation_subject_scores,
        )

        # Apply diversity filter
        diversified = self._diversity_filter(ranked, read_policy)

        # Apply budget
        selected = self._apply_budget(diversified, read_policy)

        relation_lines: list[str] = []
        if read_policy.include_relations:
            relation_budget_items = (
                [] if bool(getattr(read_policy, "relation_only_mode", False)) else selected
            )
            relation_lines = self._select_relation_lines_with_budget(
                relations=relation_ranked,
                selected_items=relation_budget_items,
                policy=read_policy,
                max_lines=max(0, int(read_policy.max_relation_lines)),
            )
            # In relation-only mode, suppress item lines only when relation context exists.
            if bool(getattr(read_policy, "relation_only_mode", False)) and relation_lines:
                selected = []

        if not selected and not relation_lines:
            return ""

        # Format for prompt injection
        return self._format_memory_block(selected, relation_lines=relation_lines)

    def _rank_items(
        self,
        items: list[MemoryItem],
        policy: MemoryReadPolicy,
        query_text: str | None = None,
        vector_similarity: dict[str, float] | None = None,
        relation_subject_scores: dict[str, float] | None = None,
    ) -> list[tuple[MemoryItem, float]]:
        """Score and rank items by hybrid criteria."""
        scored: list[tuple[MemoryItem, float]] = []
        vector_scores = vector_similarity or {}
        relation_scores = relation_subject_scores or {}
        recency_w, importance_w, similarity_w, relation_w = self._get_item_weights(policy)

        for item in items:
            recency = _time_decay(item.updated_at)
            importance = item.importance
            lexical_similarity = (
                _lexical_similarity(str(query_text), item.fact)
                if query_text
                else item.confidence
            )
            vector_score = vector_scores.get(item.memory_id)
            if vector_score is not None:
                # Blend vector + lexical to keep robustness for mixed-lang short queries.
                similarity = 0.7 * vector_score + 0.3 * lexical_similarity
            else:
                similarity = lexical_similarity

            relation_boost = relation_scores.get(str(item.subject_key or "").strip(), 0.0)
            score = (
                importance_w * importance
                + recency_w * recency
                + similarity_w * similarity
                + relation_w * relation_boost
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

    def _format_memory_block(
        self,
        items: list[MemoryItem],
        relation_lines: list[str] | None = None,
    ) -> str:
        """Format the full memory context block."""
        lines = ["[Long-term Memory]"]
        for rel_line in relation_lines or []:
            lines.append(rel_line)
        for item in items:
            lines.append(self._format_single_item(item))
        lines.append("[End Memory]")
        return "\n".join(lines)

    def _format_relation_line(self, relation: MemoryRelation) -> str:
        return (
            "- [relation] "
            f"{relation.subject_key} --{relation.predicate}--> {relation.object_text} "
            f"(confidence: {relation.confidence:.2f})"
        )

    def _get_item_weights(self, policy: MemoryReadPolicy) -> tuple[float, float, float, float]:
        """Resolve ranking weights from policy strategy with safe normalization."""
        strategy = str(getattr(policy, "strategy", "balanced") or "balanced").strip().lower()
        if strategy == "recency_first":
            return (0.6, 0.2, 0.2, 0.0)
        if strategy == "importance_first":
            return (0.2, 0.6, 0.2, 0.0)
        if strategy == "similarity_first":
            return (0.2, 0.2, 0.6, 0.0)
        if strategy == "relation_first":
            return (0.15, 0.2, 0.35, 0.3)

        recency_w = float(getattr(policy, "recency_weight", 0.3))
        importance_w = float(getattr(policy, "importance_weight", 0.4))
        similarity_w = float(getattr(policy, "similarity_weight", 0.3))
        total = max(1e-9, recency_w + importance_w + similarity_w)
        return (recency_w / total, importance_w / total, similarity_w / total, 0.0)

    async def _retrieve_relations(
        self,
        scope_targets: list[tuple[str, str]],
        policy: MemoryReadPolicy,
        query_text: str | None = None,
        embedding_provider=None,
        quantization_mode: str = "none",
        as_of: datetime | None = None,
    ) -> list[tuple[MemoryRelation, float]]:
        """Fetch and rank relation rows for optional graph-lite context injection."""
        if not scope_targets:
            return []
        fetch_limit = max(10, int(max(1, policy.max_relation_lines)) * 4)
        relations: list[MemoryRelation] = []
        try:
            if len(scope_targets) == 1:
                getter = getattr(self._db, "get_active_relations_for_scope", None)
                if callable(getter):
                    relations = await getter(
                        scope=scope_targets[0][0],
                        scope_id=scope_targets[0][1],
                        min_confidence=policy.min_confidence,
                        limit=fetch_limit,
                        as_of=as_of,
                    )
            else:
                getter = getattr(self._db, "get_active_relations_for_scopes", None)
                if callable(getter):
                    relations = await getter(
                        scopes=scope_targets,
                        min_confidence=policy.min_confidence,
                        limit=fetch_limit * len(scope_targets),
                        as_of=as_of,
                    )
        except Exception as e:
            logger.debug("LTM relation retrieval failed: %s", e)
            return []

        if not relations:
            return []

        vector_similarity: dict[str, float] = {}
        if query_text and bool(getattr(policy, "relation_use_vector", True)):
            vector_similarity = await self._compute_relation_vector_similarity(
                query_text=query_text,
                relations=relations,
                embedding_provider=embedding_provider,
                quantization_mode=quantization_mode,
            )

        return self._rank_relations(
            relations,
            query_text=query_text,
            policy=policy,
            vector_similarity=vector_similarity,
        )

    def _rank_relations(
        self,
        relations: list[MemoryRelation],
        query_text: str | None,
        policy: MemoryReadPolicy,
        vector_similarity: dict[str, float] | None = None,
    ) -> list[tuple[MemoryRelation, float]]:
        strategy = str(getattr(policy, "strategy", "balanced") or "balanced").strip().lower()
        scored: list[tuple[MemoryRelation, float]] = []
        vector_scores = vector_similarity or {}
        for relation in relations:
            recency = _time_decay(relation.updated_at)
            confidence = float(relation.confidence)
            if query_text:
                rel_text = self._relation_to_text(relation)
                lexical_similarity = _lexical_similarity(query_text, rel_text)
                vector_score = vector_scores.get(relation.relation_id)
                if vector_score is not None:
                    # Blend vector + lexical for better multilingual robustness.
                    similarity = 0.7 * vector_score + 0.3 * lexical_similarity
                else:
                    similarity = lexical_similarity
            else:
                similarity = confidence

            if strategy == "relation_first":
                score = 0.55 * similarity + 0.3 * confidence + 0.15 * recency
            elif strategy == "recency_first":
                score = 0.55 * recency + 0.25 * confidence + 0.2 * similarity
            else:
                score = 0.45 * similarity + 0.35 * confidence + 0.2 * recency
            scored.append((relation, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _build_relation_subject_scores(
        self,
        relation_ranked: list[tuple[MemoryRelation, float]],
    ) -> dict[str, float]:
        """Build subject-level boost scores from ranked relations."""
        if not relation_ranked:
            return {}

        scores: dict[str, float] = {}
        top_n = min(20, len(relation_ranked))
        for idx, (relation, rel_score) in enumerate(relation_ranked[:top_n]):
            key = str(relation.subject_key or "").strip()
            if not key:
                continue
            rank_decay = 1.0 - (idx / max(1.0, float(top_n)))
            boost = max(0.0, min(1.0, float(rel_score))) * rank_decay
            prev = scores.get(key, 0.0)
            if boost > prev:
                scores[key] = boost
        return scores

    def _select_relation_lines_with_budget(
        self,
        relations: list[tuple[MemoryRelation, float]],
        selected_items: list[MemoryItem],
        policy: MemoryReadPolicy,
        max_lines: int,
    ) -> list[str]:
        if max_lines <= 0 or not relations:
            return []

        used_tokens = _estimate_tokens("[Long-term Memory]\n[End Memory]\n")
        for item in selected_items:
            used_tokens += _estimate_tokens(self._format_single_item(item))

        lines: list[str] = []
        for relation, _ in relations:
            if len(lines) >= max_lines:
                break
            line = self._format_relation_line(relation)
            line_tokens = _estimate_tokens(line)
            if used_tokens + line_tokens > policy.max_tokens:
                continue
            lines.append(line)
            used_tokens += line_tokens
        return lines

    @staticmethod
    def _relation_to_text(relation: MemoryRelation) -> str:
        return f"{relation.subject_key} {relation.predicate} {relation.object_text}"

    @staticmethod
    def _cosine_similarity(query_vec: list[float], fact_vec: list[float]) -> float:
        if not query_vec or not fact_vec or len(query_vec) != len(fact_vec):
            return 0.0
        q_norm = sqrt(sum(float(v) * float(v) for v in query_vec))
        f_norm = sqrt(sum(float(v) * float(v) for v in fact_vec))
        if q_norm <= 1e-12 or f_norm <= 1e-12:
            return 0.0
        dot = sum(float(a) * float(b) for a, b in zip(query_vec, fact_vec))
        cosine = dot / (q_norm * f_norm)
        cosine = max(-1.0, min(1.0, cosine))
        # Normalize [-1, 1] -> [0, 1] for score blending.
        return (cosine + 1.0) / 2.0

    @staticmethod
    def _normalize_vector_quantization_mode(mode: str | None) -> str:
        normalized = str(mode or "none").strip().lower()
        if normalized in {"int8", "i8", "q8"}:
            return "int8"
        return "none"

    @staticmethod
    def _quantize_vector_int8(vec: list[float]) -> list[int]:
        if not vec:
            return []
        max_abs = max(abs(float(v)) for v in vec)
        if max_abs <= 1e-12:
            return [0 for _ in vec]
        scale = 127.0 / max_abs
        quantized: list[int] = []
        for raw in vec:
            q = int(round(float(raw) * scale))
            quantized.append(max(-127, min(127, q)))
        return quantized

    @staticmethod
    def _cosine_similarity_int8(query_vec: list[int], fact_vec: list[int]) -> float:
        if not query_vec or not fact_vec or len(query_vec) != len(fact_vec):
            return 0.0
        q_norm = sqrt(sum(int(v) * int(v) for v in query_vec))
        f_norm = sqrt(sum(int(v) * int(v) for v in fact_vec))
        if q_norm <= 1e-12 or f_norm <= 1e-12:
            return 0.0
        dot = sum(int(a) * int(b) for a, b in zip(query_vec, fact_vec))
        cosine = dot / (q_norm * f_norm)
        cosine = max(-1.0, min(1.0, cosine))
        return (cosine + 1.0) / 2.0

    async def _compute_vector_similarity(
        self,
        query_text: str,
        items: list[MemoryItem],
        embedding_provider,
        quantization_mode: str = "none",
    ) -> dict[str, float]:
        """Compute query/item similarity with optional embedding provider."""
        if not query_text or not items or embedding_provider is None:
            return {}

        get_embeddings = getattr(embedding_provider, "get_embeddings", None)
        get_embedding = getattr(embedding_provider, "get_embedding", None)
        if not callable(get_embeddings) and not callable(get_embedding):
            return {}

        texts = [query_text] + [item.fact for item in items]

        vectors: list[list[float]] = []
        try:
            if callable(get_embeddings):
                raw_vectors = await get_embeddings(texts)
                if isinstance(raw_vectors, list):
                    vectors = [list(vec) for vec in raw_vectors if isinstance(vec, list)]

            if len(vectors) != len(texts) and callable(get_embedding):
                vectors = []
                for text in texts:
                    vec = await get_embedding(text)
                    if not isinstance(vec, list):
                        raise TypeError("embedding provider returned non-list vector")
                    vectors.append([float(v) for v in vec])
        except Exception as e:
            logger.debug("LTM vector similarity failed, fallback to lexical: %s", e)
            return {}

        if len(vectors) != len(texts):
            return {}

        query_vec = vectors[0]
        use_int8 = self._normalize_vector_quantization_mode(quantization_mode) == "int8"
        query_vec_i8 = self._quantize_vector_int8(query_vec) if use_int8 else None
        result: dict[str, float] = {}
        for item, vec in zip(items, vectors[1:]):
            try:
                if use_int8 and query_vec_i8 is not None:
                    result[item.memory_id] = self._cosine_similarity_int8(
                        query_vec_i8,
                        self._quantize_vector_int8(vec),
                    )
                else:
                    result[item.memory_id] = self._cosine_similarity(query_vec, vec)
            except Exception:
                continue
        return result

    async def _compute_relation_vector_similarity(
        self,
        query_text: str,
        relations: list[MemoryRelation],
        embedding_provider,
        quantization_mode: str = "none",
    ) -> dict[str, float]:
        """Compute query/relation similarity with optional embedding provider."""
        if not query_text or not relations or embedding_provider is None:
            return {}

        get_embeddings = getattr(embedding_provider, "get_embeddings", None)
        get_embedding = getattr(embedding_provider, "get_embedding", None)
        if not callable(get_embeddings) and not callable(get_embedding):
            return {}

        texts = [query_text] + [self._relation_to_text(relation) for relation in relations]

        vectors: list[list[float]] = []
        try:
            if callable(get_embeddings):
                raw_vectors = await get_embeddings(texts)
                if isinstance(raw_vectors, list):
                    vectors = [list(vec) for vec in raw_vectors if isinstance(vec, list)]

            if len(vectors) != len(texts) and callable(get_embedding):
                vectors = []
                for text in texts:
                    vec = await get_embedding(text)
                    if not isinstance(vec, list):
                        raise TypeError("embedding provider returned non-list vector")
                    vectors.append([float(v) for v in vec])
        except Exception as e:
            logger.debug("LTM relation vector similarity failed, fallback to lexical: %s", e)
            return {}

        if len(vectors) != len(texts):
            return {}

        query_vec = vectors[0]
        use_int8 = self._normalize_vector_quantization_mode(quantization_mode) == "int8"
        query_vec_i8 = self._quantize_vector_int8(query_vec) if use_int8 else None
        result: dict[str, float] = {}
        for relation, vec in zip(relations, vectors[1:]):
            try:
                if use_int8 and query_vec_i8 is not None:
                    result[relation.relation_id] = self._cosine_similarity_int8(
                        query_vec_i8,
                        self._quantize_vector_int8(vec),
                    )
                else:
                    result[relation.relation_id] = self._cosine_similarity(query_vec, vec)
            except Exception:
                continue
        return result

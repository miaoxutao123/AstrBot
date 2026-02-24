"""Write pipeline for the Long-Term Memory system.

Handles event recording, candidate extraction, dedup/merge,
confidence scoring, and policy-gated persistence.
"""

import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone

from astrbot import logger
from astrbot.core.provider.provider import Provider

from .db import MemoryDB
from .extractor import extract_candidates
from .policy import DEFAULT_RETENTION_DAYS, MemoryWritePolicy


# Source quality weights for confidence scoring
_SOURCE_QUALITY = {
    "user_explicit": 1.0,
    "llm_extract": 0.8,
    "rule": 0.85,
    "tool_result": 0.7,
}

_RETRY_MAX_ATTEMPTS = 5
_RETRY_BASE_DELAY_SECONDS = 30
_RETRY_MAX_DELAY_SECONDS = 1800


def _compute_priority_score(
    importance: float,
    confidence: float,
    recency: float = 1.0,
) -> float:
    """Compute a priority score for eviction comparison.

    Higher score = higher priority = less likely to be evicted.
    """
    return importance * 0.4 + recency * 0.3 + confidence * 0.3


def _normalize_subject_key(subject_key: str | None, fallback_fact_key: str) -> str:
    """Normalize subject key; fallback to fact_key for compatibility."""
    raw = str(subject_key or "").strip().lower()
    if not raw:
        raw = str(fallback_fact_key or "").strip().lower()
    raw = re.sub(r"[^\w\s]", "", raw)
    raw = re.sub(r"\s+", "_", raw)
    return raw[:128]


def _normalize_relation_predicate(raw_predicate: str | None, fallback_type: str) -> str:
    """Normalize relation predicate and enforce short stable key format."""
    raw = str(raw_predicate or "").strip().lower()
    if not raw:
        raw = f"{str(fallback_type or 'memory').strip().lower()}_fact"
    raw = re.sub(r"[^\w\s]", "", raw)
    raw = re.sub(r"\s+", "_", raw)
    raw = raw.strip("_")
    if not raw:
        raw = "memory_fact"
    return raw[:64]


def _normalize_relation_object(raw_object: str | None, fallback_fact: str) -> str:
    """Normalize relation object text with bounded size."""
    text = str(raw_object or "").strip()
    if not text:
        text = str(fallback_fact or "").strip()
    text = " ".join(text.split())
    return text[:500]


class MemoryWriter:
    """Manages the write pipeline: event → extract → dedup → score → persist."""

    def __init__(self, memory_db: MemoryDB) -> None:
        self._db = memory_db
        # Rate-limit tracking: scope_id → list of write timestamps
        self._session_write_counts: dict[str, int] = defaultdict(int)
        self._hourly_writes: list[float] = []

    def _prune_hourly_writes(self) -> None:
        cutoff = time.time() - 3600
        self._hourly_writes = [t for t in self._hourly_writes if t > cutoff]

    async def _schedule_retry(self, event_ids: list[str], error: str) -> None:
        retried, dead_lettered = await self._db.mark_events_retry(
            event_ids,
            error=error,
            max_attempts=_RETRY_MAX_ATTEMPTS,
            base_delay_seconds=_RETRY_BASE_DELAY_SECONDS,
            max_delay_seconds=_RETRY_MAX_DELAY_SECONDS,
        )
        logger.warning(
            "LTM events retry scheduled: retried=%d dead_letter=%d error=%s",
            retried,
            dead_lettered,
            str(error)[:200],
        )

    async def _apply_temporal_supersede(
        self,
        *,
        scope: str,
        scope_id: str,
        mem_type: str,
        subject_key: str,
        fact_key: str,
        new_memory_id: str,
        write_policy: MemoryWritePolicy,
        supersede_at: datetime | None = None,
    ) -> int:
        """Supersede older active items that represent the same subject concept."""
        if not write_policy.enable_temporal_supersede:
            return 0
        if mem_type not in set(write_policy.temporal_conflict_types):
            return 0
        if not subject_key:
            return 0

        conflicts = await self._db.get_conflicting_items_by_subject(
            scope=scope,
            scope_id=scope_id,
            type=mem_type,
            subject_key=subject_key,
            exclude_fact_key=fact_key,
            limit=20,
        )
        conflict_ids = [
            item.memory_id
            for item in conflicts
            if item.memory_id != new_memory_id
        ]
        if not conflict_ids:
            return 0

        superseded = await self._db.supersede_items(
            conflict_ids,
            superseded_by=new_memory_id,
            invalid_at=supersede_at,
        )
        if superseded > 0:
            logger.debug(
                "LTM temporal supersede: [%s/%s] type=%s subject=%s superseded=%d",
                scope,
                scope_id,
                mem_type,
                subject_key,
                superseded,
            )
        return superseded

    async def _sync_relation_for_item(
        self,
        *,
        scope: str,
        scope_id: str,
        memory_id: str,
        mem_type: str,
        subject_key: str,
        fact: str,
        confidence: float,
        evidence_count: int,
        candidate: dict,
        now: datetime | None = None,
    ) -> None:
        """Sync graph-lite relation row for an active memory item."""
        if mem_type not in {"profile", "preference", "task_state", "constraint"}:
            return

        predicate = _normalize_relation_predicate(
            candidate.get("relation_predicate"),
            mem_type,
        )
        object_text = _normalize_relation_object(
            candidate.get("relation_object"),
            fact,
        )
        if not subject_key or not predicate or not object_text:
            return

        relation = await self._db.upsert_relation(
            scope=scope,
            scope_id=scope_id,
            subject_key=subject_key,
            predicate=predicate,
            object_text=object_text,
            confidence=max(0.0, min(1.0, float(confidence))),
            evidence_count=max(1, int(evidence_count)),
            memory_id=memory_id,
            memory_type=mem_type,
            now=now or datetime.now(timezone.utc),
        )
        if relation is not None:
            logger.debug(
                "LTM relation upserted: [%s/%s] %s --%s--> %s",
                scope,
                scope_id,
                subject_key,
                predicate,
                object_text[:80],
            )

    def _resolve_status_for_policy(
        self,
        mem_type: str,
        write_policy: MemoryWritePolicy,
    ) -> str:
        if write_policy.mode == "shadow":
            return "shadow"
        if write_policy.mode == "auto":
            if mem_type in write_policy.require_approval_types:
                return "shadow"
            return "active"
        # manual mode
        return "shadow"

    def _build_event_message_text(self, event) -> str:
        source_type = getattr(event, "source_type", "message")
        content = event.content
        if not isinstance(content, dict):
            return str(content or "").strip()

        text = content.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        if source_type == "tool_result":
            tool_name = None
            tool_field = content.get("tool")
            if isinstance(tool_field, dict):
                tool_name = tool_field.get("name")
            if not tool_name:
                tool_name = content.get("tool_name")

            result = content.get("result")
            error = content.get("error")
            parts: list[str] = []
            if tool_name:
                parts.append(f"[tool:{str(tool_name)[:80]}]")
            if isinstance(error, str) and error.strip():
                parts.append(f"error={error.strip()[:200]}")
            if result is not None:
                if isinstance(result, str):
                    result_text = result
                elif isinstance(result, dict) and isinstance(result.get("text"), str):
                    result_text = result.get("text", "")
                else:
                    try:
                        result_text = json.dumps(result, ensure_ascii=False)
                    except Exception:
                        result_text = str(result)
                result_text = " ".join(str(result_text).split())
                if result_text:
                    parts.append(f"result={result_text[:500]}")
            return " ".join(parts).strip()

        return ""

    async def record_event(
        self,
        scope: str,
        scope_id: str,
        source_type: str,
        source_role: str,
        content: dict,
        platform_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """Record a raw event. Returns the event_id."""
        event = await self._db.insert_event(
            scope=scope,
            scope_id=scope_id,
            source_type=source_type,
            source_role=source_role,
            content=content,
            platform_id=platform_id,
            session_id=session_id,
        )
        return event.event_id

    async def process_pending_events(
        self,
        provider: Provider,
        write_policy: MemoryWritePolicy,
        retention_days: dict[str, int] | None = None,
        batch_size: int = 20,
    ) -> int:
        """Process unprocessed events: extract candidates and persist.

        Returns the number of new memory items created/updated.
        """
        if not write_policy.enable:
            return 0

        events = await self._db.get_unprocessed_events(limit=batch_size)
        if not events:
            return 0

        retention = retention_days or DEFAULT_RETENTION_DAYS
        total_writes = 0

        # Group events by (scope, scope_id) for batch extraction
        grouped: dict[tuple[str, str], list] = defaultdict(list)
        for event in events:
            grouped[(event.scope, event.scope_id)].append(event)

        for (scope, scope_id), scope_events in grouped.items():
            scope_event_ids = [e.event_id for e in scope_events]
            scope_had_errors = False
            # Build message list for extraction
            messages = []
            for evt in scope_events:
                text = self._build_event_message_text(evt)
                if text:
                    messages.append({
                        "role": evt.source_role,
                        "content": text,
                    })

            if not messages:
                await self._db.mark_events_processed(
                    scope_event_ids
                )
                continue

            # Extract candidates
            try:
                candidates = await extract_candidates(
                    provider=provider,
                    messages=messages,
                    session_id=scope_id,
                )
            except Exception as e:
                logger.warning("LTM extraction failed for scope %s/%s: %s", scope, scope_id, e)
                await self._schedule_retry(scope_event_ids, error=f"extract: {e!s}")
                continue

            # Process each candidate through the pipeline
            first_error: Exception | None = None
            for candidate in candidates:
                try:
                    written = await self._process_candidate(
                        scope=scope,
                        scope_id=scope_id,
                        candidate=candidate,
                        event_ids=scope_event_ids,
                        write_policy=write_policy,
                        retention=retention,
                    )
                    if written:
                        total_writes += 1
                except Exception as e:
                    logger.warning("LTM candidate processing error: %s", e)
                    scope_had_errors = True
                    if first_error is None:
                        first_error = e

            # Candidate pipeline had runtime errors — retry with backoff/dead-letter.
            if scope_had_errors:
                await self._schedule_retry(
                    scope_event_ids,
                    error=f"pipeline: {first_error!s}" if first_error else "pipeline error",
                )
                continue

            # Mark events as processed
            await self._db.mark_events_processed(scope_event_ids)

        return total_writes

    async def _process_candidate(
        self,
        scope: str,
        scope_id: str,
        candidate: dict,
        event_ids: list[str],
        write_policy: MemoryWritePolicy,
        retention: dict[str, int],
    ) -> bool:
        """Process a single candidate through dedup, scoring, and policy gate.

        Returns True if a memory item was created or updated.
        """
        mem_type = candidate.get("type")
        fact = candidate.get("fact")
        fact_key = candidate.get("fact_key")
        subject_key = _normalize_subject_key(candidate.get("subject_key"), str(fact_key or ""))
        base_confidence = candidate.get("confidence", 0.5)
        importance = candidate.get("importance", 0.5)

        if not mem_type or not fact or not fact_key:
            logger.debug("LTM candidate missing required fields: %s", list(candidate.keys()))
            return False

        # Policy check: allowed type
        if mem_type not in write_policy.allowed_types:
            return False

        # Dedup: check for existing item with same fact_key first.
        # Existing-item merges should not be blocked by scope size limits.
        existing = await self._db.get_item_by_fact_key(scope, scope_id, fact_key)
        evidence_event_ids = list(dict.fromkeys(event_ids[:3]))

        source_weight = _SOURCE_QUALITY.get("llm_extract", 0.8)
        if existing:
            # Idempotency: only count newly-linked evidence events.
            linked = await self._db.get_existing_evidence_event_ids(
                existing.memory_id,
                evidence_event_ids,
            )
            new_event_ids = [eid for eid in evidence_event_ids if eid not in linked]
            added_evidence = len(new_event_ids)

            new_evidence_count = existing.evidence_count
            new_confidence = existing.confidence
            new_fact = existing.fact
            new_subject_key = existing.subject_key or subject_key
            new_importance = max(existing.importance, importance)
            new_status = existing.status

            if added_evidence > 0:
                new_evidence_count = existing.evidence_count + added_evidence
                repetition_bonus = min(1.5, 1.0 + 0.1 * (new_evidence_count - 1))
                scored_confidence = min(
                    1.0,
                    base_confidence * source_weight * repetition_bonus,
                )
                # Weighted average by newly added evidence.
                new_confidence = (
                    existing.confidence * existing.evidence_count
                    + scored_confidence * added_evidence
                ) / new_evidence_count
                if scored_confidence > existing.confidence:
                    new_fact = fact

            if (
                existing.status == "shadow"
                and new_evidence_count >= max(1, write_policy.min_evidence_count)
            ):
                new_status = self._resolve_status_for_policy(mem_type, write_policy)

            if (
                new_fact != existing.fact
                or new_subject_key != existing.subject_key
                or new_confidence != existing.confidence
                or new_importance != existing.importance
                or new_evidence_count != existing.evidence_count
                or new_status != existing.status
            ):
                await self._db.update_item(
                    existing.memory_id,
                    fact=new_fact,
                    subject_key=new_subject_key,
                    confidence=min(1.0, new_confidence),
                    importance=new_importance,
                    evidence_count=new_evidence_count,
                    status=new_status,
                )
                item_updated = True
            else:
                item_updated = False

            # Link only newly-seen evidence events.
            for eid in new_event_ids:
                await self._db.insert_evidence(
                    memory_id=existing.memory_id,
                    event_id=eid,
                    extraction_method="llm_extract",
                )

            if new_status == "active":
                await self._apply_temporal_supersede(
                    scope=scope,
                    scope_id=scope_id,
                    mem_type=mem_type,
                    subject_key=new_subject_key,
                    fact_key=existing.fact_key,
                    new_memory_id=existing.memory_id,
                    write_policy=write_policy,
                    supersede_at=datetime.now(timezone.utc),
                )
                await self._sync_relation_for_item(
                    scope=scope,
                    scope_id=scope_id,
                    memory_id=existing.memory_id,
                    mem_type=mem_type,
                    subject_key=new_subject_key,
                    fact=new_fact,
                    confidence=min(1.0, float(new_confidence)),
                    evidence_count=new_evidence_count,
                    candidate=candidate,
                )

            return item_updated or bool(new_event_ids)

        # New item path: apply rate limits and scope limits
        self._prune_hourly_writes()
        if len(self._hourly_writes) >= write_policy.max_writes_per_hour:
            logger.debug("LTM hourly write limit reached")
            return False

        session_key = f"{scope}:{scope_id}"
        if self._session_write_counts[session_key] >= write_policy.max_writes_per_session:
            logger.debug("LTM session write limit reached for %s", session_key)
            return False

        # Policy check: max items per scope (smart eviction)
        current_count = await self._db.count_items_for_scope(scope, scope_id)
        if current_count >= write_policy.max_items_per_scope:
            if not write_policy.eviction_enabled:
                logger.debug("LTM scope item limit reached for %s/%s (eviction disabled)", scope, scope_id)
                return False

            # Smart eviction: compare new candidate against lowest-priority existing
            new_score = _compute_priority_score(importance, base_confidence)
            victims = await self._db.get_eviction_candidates(scope, scope_id, limit=1)
            if not victims:
                logger.debug("LTM scope full, no eviction candidates for %s/%s", scope, scope_id)
                return False

            victim = victims[0]
            victim_score = _compute_priority_score(victim.importance, victim.confidence)
            if new_score <= victim_score:
                logger.debug(
                    "LTM eviction skipped: new score %.3f <= victim score %.3f",
                    new_score, victim_score,
                )
                return False

            # Evict the lowest-priority item
            await self._db.update_item(victim.memory_id, status="expired")
            logger.debug(
                "LTM evicted [%s] %s (score=%.3f) to make room for new item (score=%.3f)",
                victim.type, victim.fact_key, victim_score, new_score,
            )
        elif (
            write_policy.eviction_enabled
            and current_count >= int(write_policy.max_items_per_scope * write_policy.eviction_buffer_ratio)
        ):
            # Approaching limit — log a warning but still allow writes
            logger.debug(
                "LTM scope %s/%s at %d/%d items (%.0f%% buffer threshold)",
                scope, scope_id, current_count, write_policy.max_items_per_scope,
                write_policy.eviction_buffer_ratio * 100,
            )

        # New item: apply confidence threshold
        scored_confidence = min(1.0, base_confidence * source_weight)
        if scored_confidence < write_policy.min_confidence:
            return False

        # Determine status based on policy mode + evidence gate.
        status = self._resolve_status_for_policy(mem_type, write_policy)
        if 1 < max(1, write_policy.min_evidence_count):
            status = "shadow"

        # Determine TTL
        ttl = retention.get(mem_type)
        if ttl is not None and ttl < 0:
            ttl = None  # Permanent

        # Create new item
        now = datetime.now(timezone.utc)
        item = await self._db.insert_item(
            scope=scope,
            scope_id=scope_id,
            type=mem_type,
            fact=fact,
            fact_key=fact_key,
            subject_key=subject_key,
            confidence=scored_confidence,
            importance=importance,
            evidence_count=1,
            ttl_days=ttl,
            status=status,
            valid_at=now,
        )

        # Link evidence
        for eid in evidence_event_ids:
            try:
                await self._db.insert_evidence(
                    memory_id=item.memory_id,
                    event_id=eid,
                    extraction_method="llm_extract",
                )
            except Exception:
                pass

        # Track rate limits
        self._hourly_writes.append(time.time())
        self._session_write_counts[session_key] += 1

        if item.status == "active":
            await self._apply_temporal_supersede(
                scope=scope,
                scope_id=scope_id,
                mem_type=mem_type,
                subject_key=subject_key,
                fact_key=fact_key,
                new_memory_id=item.memory_id,
                write_policy=write_policy,
                supersede_at=now,
            )
            await self._sync_relation_for_item(
                scope=scope,
                scope_id=scope_id,
                memory_id=item.memory_id,
                mem_type=mem_type,
                subject_key=subject_key,
                fact=fact,
                confidence=scored_confidence,
                evidence_count=1,
                candidate=candidate,
                now=now,
            )

        logger.debug(
            "LTM new item: [%s/%s] %s = %s (confidence=%.2f, status=%s, subject=%s)",
            scope, scope_id, mem_type, fact[:60], scored_confidence, status, subject_key,
        )
        return True

    def reset_session_counts(self) -> None:
        """Reset per-session write counters (call at session boundary)."""
        self._session_write_counts.clear()

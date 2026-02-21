"""Write pipeline for the Long-Term Memory system.

Handles event recording, candidate extraction, dedup/merge,
confidence scoring, and policy-gated persistence.
"""

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


def _compute_priority_score(
    importance: float,
    confidence: float,
    recency: float = 1.0,
) -> float:
    """Compute a priority score for eviction comparison.

    Higher score = higher priority = less likely to be evicted.
    """
    return importance * 0.4 + recency * 0.3 + confidence * 0.3


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
                content = evt.content
                if isinstance(content, dict):
                    messages.append({
                        "role": evt.source_role,
                        "content": content.get("text", str(content)),
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
                # Keep events unprocessed so they can be retried in next cycle.
                continue

            # Process each candidate through the pipeline
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

            # If candidate pipeline had runtime errors, keep events pending for retry.
            if scope_had_errors:
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

        source_weight = _SOURCE_QUALITY.get("llm_extract", 0.8)
        if existing:
            # Merge: update existing item
            new_evidence_count = existing.evidence_count + 1
            repetition_bonus = min(1.0, 1.0 + 0.1 * (new_evidence_count - 1))
            scored_confidence = min(1.0, base_confidence * source_weight * repetition_bonus)

            # Weighted average of confidence
            avg_confidence = (
                existing.confidence * existing.evidence_count + scored_confidence
            ) / new_evidence_count

            # Update fact if new confidence is higher
            new_fact = fact if scored_confidence > existing.confidence else existing.fact

            await self._db.update_item(
                existing.memory_id,
                fact=new_fact,
                confidence=min(1.0, avg_confidence),
                importance=max(existing.importance, importance),
                evidence_count=new_evidence_count,
            )

            # Link evidence
            for eid in event_ids[:3]:  # Limit evidence links
                try:
                    await self._db.insert_evidence(
                        memory_id=existing.memory_id,
                        event_id=eid,
                        extraction_method="llm_extract",
                    )
                except Exception:
                    pass  # Duplicate evidence link

            return True

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

        # Determine status based on policy mode
        if write_policy.mode == "shadow":
            status = "shadow"
        elif write_policy.mode == "auto":
            if mem_type in write_policy.require_approval_types:
                status = "shadow"
            else:
                status = "active"
        else:  # manual
            status = "shadow"

        # Determine TTL
        ttl = retention.get(mem_type)
        if ttl is not None and ttl < 0:
            ttl = None  # Permanent

        # Create new item
        item = await self._db.insert_item(
            scope=scope,
            scope_id=scope_id,
            type=mem_type,
            fact=fact,
            fact_key=fact_key,
            confidence=scored_confidence,
            importance=importance,
            evidence_count=1,
            ttl_days=ttl,
            status=status,
        )

        # Link evidence
        for eid in event_ids[:3]:
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

        logger.debug(
            "LTM new item: [%s/%s] %s = %s (confidence=%.2f, status=%s)",
            scope, scope_id, mem_type, fact[:60], scored_confidence, status,
        )
        return True

    def reset_session_counts(self) -> None:
        """Reset per-session write counters (call at session boundary)."""
        self._session_write_counts.clear()

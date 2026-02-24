"""Database operations for the Long-Term Memory system.

Provides async CRUD for MemoryEvent, MemoryItem, and MemoryEvidence tables.
Designed to be used by LTMManager and the dashboard API.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, desc, func, select, update

from astrbot.core.db import BaseDatabase

from .models import MemoryEvent, MemoryEvidence, MemoryItem, MemoryRelation


class MemoryDB:
    """Thin wrapper around BaseDatabase for LTM table operations."""

    def __init__(self, db: BaseDatabase) -> None:
        self._db = db

    # ------------------------------------------------------------------ #
    #  MemoryEvent
    # ------------------------------------------------------------------ #

    async def insert_event(
        self,
        scope: str,
        scope_id: str,
        source_type: str,
        source_role: str,
        content: dict,
        platform_id: str | None = None,
        session_id: str | None = None,
    ) -> MemoryEvent:
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                event = MemoryEvent(
                    scope=scope,
                    scope_id=scope_id,
                    source_type=source_type,
                    source_role=source_role,
                    content=content,
                    platform_id=platform_id,
                    session_id=session_id,
                )
                session.add(event)
                await session.flush()
                await session.refresh(event)
                return event

    async def get_unprocessed_events(
        self,
        limit: int = 50,
        now: datetime | None = None,
    ) -> list[MemoryEvent]:
        retry_now = now or datetime.now(timezone.utc)
        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryEvent)
                .where(
                    MemoryEvent.processed == False,  # noqa: E712
                    MemoryEvent.dead_letter == False,  # noqa: E712
                    or_(
                        MemoryEvent.next_retry_at.is_(None),
                        MemoryEvent.next_retry_at <= retry_now,
                    ),
                )
                .order_by(
                    func.coalesce(
                        MemoryEvent.next_retry_at,
                        MemoryEvent.created_at,
                    ),
                    MemoryEvent.created_at,
                )
                .limit(limit)
            )
            return list(result.scalars().all())

    async def mark_events_processed(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                await session.execute(
                    update(MemoryEvent)
                    .where(col(MemoryEvent.event_id).in_(event_ids))
                    .values(
                        processed=True,
                        next_retry_at=None,
                        last_error=None,
                    )
                )

    async def mark_events_retry(
        self,
        event_ids: list[str],
        *,
        error: str,
        max_attempts: int = 5,
        base_delay_seconds: int = 30,
        max_delay_seconds: int = 3600,
    ) -> tuple[int, int]:
        """Increase retry attempts and schedule backoff / dead-letter.

        Returns (retried_count, dead_lettered_count).
        """
        if not event_ids:
            return (0, 0)

        now = datetime.now(timezone.utc)
        retried = 0
        dead_lettered = 0
        safe_error = str(error or "")[:500]

        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                result = await session.execute(
                    select(MemoryEvent).where(
                        col(MemoryEvent.event_id).in_(event_ids),
                        MemoryEvent.processed == False,  # noqa: E712
                        MemoryEvent.dead_letter == False,  # noqa: E712
                    )
                )
                rows = list(result.scalars().all())
                for row in rows:
                    next_attempt = int(row.attempt_count or 0) + 1
                    values: dict = {
                        "attempt_count": next_attempt,
                        "last_error": safe_error,
                    }
                    if next_attempt >= max_attempts:
                        values["dead_letter"] = True
                        values["next_retry_at"] = None
                        dead_lettered += 1
                    else:
                        delay = min(
                            max_delay_seconds,
                            base_delay_seconds * (2 ** max(0, next_attempt - 1)),
                        )
                        values["next_retry_at"] = now + timedelta(seconds=delay)
                        retried += 1

                    await session.execute(
                        update(MemoryEvent)
                        .where(MemoryEvent.event_id == row.event_id)
                        .values(**values)
                    )

        return retried, dead_lettered

    async def list_events(
        self,
        scope: str | None = None,
        scope_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[MemoryEvent], int]:
        async with self._db.get_db() as session:
            session: AsyncSession
            query = select(MemoryEvent)
            count_query = select(func.count()).select_from(MemoryEvent)

            if scope:
                query = query.where(MemoryEvent.scope == scope)
                count_query = count_query.where(MemoryEvent.scope == scope)
            if scope_id:
                query = query.where(MemoryEvent.scope_id == scope_id)
                count_query = count_query.where(MemoryEvent.scope_id == scope_id)

            total = (await session.execute(count_query)).scalar_one()
            offset = (page - 1) * page_size
            result = await session.execute(
                query.order_by(desc(MemoryEvent.created_at))
                .offset(offset)
                .limit(page_size)
            )
            return list(result.scalars().all()), total

    # ------------------------------------------------------------------ #
    #  MemoryItem
    # ------------------------------------------------------------------ #

    async def insert_item(
        self,
        scope: str,
        scope_id: str,
        type: str,
        fact: str,
        fact_key: str,
        subject_key: str | None = None,
        confidence: float = 0.5,
        importance: float = 0.5,
        evidence_count: int = 1,
        ttl_days: int | None = None,
        status: str = "shadow",
        valid_at: datetime | None = None,
        invalid_at: datetime | None = None,
        superseded_by: str | None = None,
    ) -> MemoryItem:
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                item = MemoryItem(
                    scope=scope,
                    scope_id=scope_id,
                    type=type,
                    fact=fact,
                    fact_key=fact_key,
                    subject_key=subject_key,
                    confidence=confidence,
                    importance=importance,
                    evidence_count=evidence_count,
                    ttl_days=ttl_days,
                    status=status,
                    valid_at=valid_at,
                    invalid_at=invalid_at,
                    superseded_by=superseded_by,
                )
                session.add(item)
                await session.flush()
                await session.refresh(item)
                return item

    async def get_item_by_id(self, memory_id: str) -> MemoryItem | None:
        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryItem).where(MemoryItem.memory_id == memory_id)
            )
            return result.scalar_one_or_none()

    async def get_item_by_fact_key(
        self, scope: str, scope_id: str, fact_key: str
    ) -> MemoryItem | None:
        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryItem).where(
                    MemoryItem.scope == scope,
                    MemoryItem.scope_id == scope_id,
                    MemoryItem.fact_key == fact_key,
                )
            )
            return result.scalar_one_or_none()

    async def list_items(
        self,
        scope: str | None = None,
        scope_id: str | None = None,
        type: str | None = None,
        status: str | None = None,
        min_confidence: float = 0.0,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[MemoryItem], int]:
        async with self._db.get_db() as session:
            session: AsyncSession
            query = select(MemoryItem)
            count_base = select(func.count()).select_from(MemoryItem)

            filters = []
            if scope:
                filters.append(MemoryItem.scope == scope)
            if scope_id:
                filters.append(MemoryItem.scope_id == scope_id)
            if type:
                filters.append(MemoryItem.type == type)
            if status:
                filters.append(MemoryItem.status == status)
            if min_confidence > 0:
                filters.append(MemoryItem.confidence >= min_confidence)

            for f in filters:
                query = query.where(f)
                count_base = count_base.where(f)

            total = (await session.execute(count_base)).scalar_one()
            offset = (page - 1) * page_size
            result = await session.execute(
                query.order_by(desc(MemoryItem.updated_at))
                .offset(offset)
                .limit(page_size)
            )
            return list(result.scalars().all()), total

    async def get_active_items_for_scope(
        self,
        scope: str,
        scope_id: str,
        min_confidence: float = 0.0,
        limit: int = 100,
        as_of: datetime | None = None,
    ) -> list[MemoryItem]:
        target_time = as_of or datetime.now(timezone.utc)
        status_filter = (
            MemoryItem.status.in_(["active", "superseded"])
            if as_of is not None
            else MemoryItem.status == "active"
        )
        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryItem)
                .where(
                    MemoryItem.scope == scope,
                    MemoryItem.scope_id == scope_id,
                    status_filter,
                    MemoryItem.confidence >= min_confidence,
                    or_(
                        MemoryItem.valid_at.is_(None),
                        MemoryItem.valid_at <= target_time,
                    ),
                    or_(
                        MemoryItem.invalid_at.is_(None),
                        MemoryItem.invalid_at > target_time,
                    ),
                )
                .order_by(
                    desc(MemoryItem.importance),
                    desc(MemoryItem.updated_at),
                )
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_active_items_for_scopes(
        self,
        scopes: list[tuple[str, str]],
        min_confidence: float = 0.0,
        limit: int = 300,
        as_of: datetime | None = None,
    ) -> list[MemoryItem]:
        """Get active items across multiple (scope, scope_id) pairs."""
        normalized_scopes: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for entry in scopes:
            if not isinstance(entry, tuple) or len(entry) != 2:
                continue
            scope, scope_id = str(entry[0]).strip(), str(entry[1]).strip()
            if not scope or not scope_id:
                continue
            key = (scope, scope_id)
            if key not in seen:
                seen.add(key)
                normalized_scopes.append(key)

        if not normalized_scopes:
            return []

        conditions = [
            and_(
                MemoryItem.scope == scope,
                MemoryItem.scope_id == scope_id,
            )
            for scope, scope_id in normalized_scopes
        ]

        target_time = as_of or datetime.now(timezone.utc)
        status_filter = (
            MemoryItem.status.in_(["active", "superseded"])
            if as_of is not None
            else MemoryItem.status == "active"
        )

        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryItem)
                .where(
                    or_(*conditions),
                    status_filter,
                    MemoryItem.confidence >= min_confidence,
                    or_(
                        MemoryItem.valid_at.is_(None),
                        MemoryItem.valid_at <= target_time,
                    ),
                    or_(
                        MemoryItem.invalid_at.is_(None),
                        MemoryItem.invalid_at > target_time,
                    ),
                )
                .order_by(
                    desc(MemoryItem.importance),
                    desc(MemoryItem.updated_at),
                )
                .limit(limit)
            )
            return list(result.scalars().all())

    async def update_item(
        self,
        memory_id: str,
        *,
        fact: str | None = None,
        subject_key: str | None = None,
        confidence: float | None = None,
        importance: float | None = None,
        evidence_count: int | None = None,
        status: str | None = None,
        valid_at: datetime | None = object,  # type: ignore[assignment]
        invalid_at: datetime | None = object,  # type: ignore[assignment]
        superseded_by: str | None = object,  # type: ignore[assignment]
        ttl_days: int | None = object,  # type: ignore[assignment]
    ) -> MemoryItem | None:
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                values: dict = {}
                if fact is not None:
                    values["fact"] = fact
                if subject_key is not None:
                    values["subject_key"] = subject_key
                if confidence is not None:
                    values["confidence"] = confidence
                if importance is not None:
                    values["importance"] = importance
                if evidence_count is not None:
                    values["evidence_count"] = evidence_count
                if status is not None:
                    values["status"] = status
                if valid_at is not object:
                    values["valid_at"] = valid_at
                if invalid_at is not object:
                    values["invalid_at"] = invalid_at
                if superseded_by is not object:
                    values["superseded_by"] = superseded_by
                if ttl_days is not object:
                    values["ttl_days"] = ttl_days
                if not values:
                    return await self.get_item_by_id(memory_id)
                values["updated_at"] = datetime.now(timezone.utc)
                await session.execute(
                    update(MemoryItem)
                    .where(MemoryItem.memory_id == memory_id)
                    .values(**values)
                )
        return await self.get_item_by_id(memory_id)

    async def delete_item(self, memory_id: str) -> None:
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                # Delete evidence links first
                await session.execute(
                    delete(MemoryEvidence).where(
                        MemoryEvidence.memory_id == memory_id
                    )
                )
                await session.execute(
                    delete(MemoryItem).where(
                        MemoryItem.memory_id == memory_id
                    )
                )

    async def count_items_for_scope(self, scope: str, scope_id: str) -> int:
        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(func.count())
                .select_from(MemoryItem)
                .where(
                    MemoryItem.scope == scope,
                    MemoryItem.scope_id == scope_id,
                    MemoryItem.status.in_(["active", "shadow"]),
                )
            )
            return result.scalar_one()

    async def get_conflicting_items_by_subject(
        self,
        scope: str,
        scope_id: str,
        type: str,
        subject_key: str,
        exclude_fact_key: str | None = None,
        limit: int = 20,
    ) -> list[MemoryItem]:
        """Find currently valid active items that conflict by subject key."""
        if not subject_key:
            return []

        now = datetime.now(timezone.utc)
        async with self._db.get_db() as session:
            session: AsyncSession
            query = (
                select(MemoryItem)
                .where(
                    MemoryItem.scope == scope,
                    MemoryItem.scope_id == scope_id,
                    MemoryItem.type == type,
                    MemoryItem.subject_key == subject_key,
                    MemoryItem.status == "active",
                    or_(MemoryItem.invalid_at.is_(None), MemoryItem.invalid_at > now),
                )
                .order_by(desc(MemoryItem.updated_at))
                .limit(limit)
            )
            if exclude_fact_key:
                query = query.where(MemoryItem.fact_key != exclude_fact_key)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def supersede_items(
        self,
        memory_ids: list[str],
        *,
        superseded_by: str,
        invalid_at: datetime | None = None,
    ) -> int:
        """Mark existing items superseded by a newer memory item."""
        if not memory_ids:
            return 0
        at_time = invalid_at or datetime.now(timezone.utc)
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                result = await session.execute(
                    update(MemoryItem)
                    .where(
                        col(MemoryItem.memory_id).in_(memory_ids),
                        MemoryItem.status == "active",
                    )
                    .values(
                        status="superseded",
                        invalid_at=at_time,
                        superseded_by=superseded_by,
                        updated_at=at_time,
                    )
                )
                return int(result.rowcount or 0)

    async def expire_old_items(self) -> int:
        """Mark items past their TTL as expired. Returns count of expired items."""
        now = datetime.now(timezone.utc)
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                # Fast path (SQLite): expire with one SQL statement.
                # julianday(now) - julianday(created_at) >= ttl_days
                if session.bind and session.bind.dialect.name == "sqlite":
                    result = await session.execute(
                        text(
                            """
                            UPDATE memory_items
                            SET status = 'expired', updated_at = :now
                            WHERE ttl_days IS NOT NULL
                              AND ttl_days > 0
                              AND status IN ('active', 'shadow')
                              AND (julianday(:now) - julianday(created_at)) >= ttl_days
                            """
                        ),
                        {"now": now},
                    )
                    return int(result.rowcount or 0)

                # Generic fallback for non-SQLite backends: chunked scan.
                batch_size = 500
                expired_count = 0
                last_id = 0
                while True:
                    batch = await session.execute(
                        select(
                            MemoryItem.id,
                            MemoryItem.memory_id,
                            MemoryItem.created_at,
                            MemoryItem.ttl_days,
                        )
                        .where(
                            MemoryItem.id > last_id,
                            MemoryItem.ttl_days.isnot(None),
                            MemoryItem.status.in_(["active", "shadow"]),
                        )
                        .order_by(MemoryItem.id)
                        .limit(batch_size)
                    )
                    rows = list(batch.all())
                    if not rows:
                        break

                    last_id = max(int(row[0]) for row in rows if row[0] is not None)
                    to_expire: list[str] = []
                    for _, memory_id, created_at, ttl_days in rows:
                        if not ttl_days or ttl_days <= 0:
                            continue
                        created = created_at
                        if created.tzinfo is None:
                            created = created.replace(tzinfo=timezone.utc)
                        expiry = created + timedelta(days=int(ttl_days))
                        if now > expiry:
                            to_expire.append(memory_id)

                    if to_expire:
                        await session.execute(
                            update(MemoryItem)
                            .where(col(MemoryItem.memory_id).in_(to_expire))
                            .values(status="expired", updated_at=now)
                        )
                        expired_count += len(to_expire)

                return expired_count

    async def get_stats(
        self,
        scope: str | None = None,
        scope_id: str | None = None,
    ) -> dict:
        async with self._db.get_db() as session:
            session: AsyncSession
            base = select(
                MemoryItem.status,
                MemoryItem.type,
                func.count().label("count"),
            ).group_by(MemoryItem.status, MemoryItem.type)

            if scope:
                base = base.where(MemoryItem.scope == scope)
            if scope_id:
                base = base.where(MemoryItem.scope_id == scope_id)

            result = await session.execute(base)
            rows = result.all()

            stats: dict = {"total": 0, "by_status": {}, "by_type": {}}
            for row in rows:
                status, mem_type, count = row
                stats["total"] += count
                stats["by_status"][status] = stats["by_status"].get(status, 0) + count
                stats["by_type"][mem_type] = stats["by_type"].get(mem_type, 0) + count
            return stats

    # ------------------------------------------------------------------ #
    #  MemoryEvidence
    # ------------------------------------------------------------------ #

    async def insert_evidence(
        self,
        memory_id: str,
        event_id: str,
        extraction_method: str,
        extraction_meta: dict | None = None,
    ) -> MemoryEvidence:
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                evidence = MemoryEvidence(
                    memory_id=memory_id,
                    event_id=event_id,
                    extraction_method=extraction_method,
                    extraction_meta=extraction_meta,
                )
                session.add(evidence)
                await session.flush()
                await session.refresh(evidence)
                return evidence

    async def get_evidence_for_item(
        self, memory_id: str
    ) -> list[MemoryEvidence]:
        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryEvidence).where(
                    MemoryEvidence.memory_id == memory_id
                )
            )
            return list(result.scalars().all())

    async def get_existing_evidence_event_ids(
        self,
        memory_id: str,
        event_ids: list[str],
    ) -> set[str]:
        """Return event_ids that are already linked to the memory item."""
        if not event_ids:
            return set()

        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryEvidence.event_id).where(
                    MemoryEvidence.memory_id == memory_id,
                    col(MemoryEvidence.event_id).in_(event_ids),
                )
            )
            return {event_id for event_id in result.scalars().all() if event_id}

    # ------------------------------------------------------------------ #
    #  MemoryRelation
    # ------------------------------------------------------------------ #

    async def insert_relation(
        self,
        scope: str,
        scope_id: str,
        subject_key: str,
        predicate: str,
        object_text: str,
        *,
        confidence: float = 0.5,
        evidence_count: int = 1,
        status: str = "active",
        valid_at: datetime | None = None,
        invalid_at: datetime | None = None,
        superseded_by: str | None = None,
        memory_id: str | None = None,
        memory_type: str | None = None,
    ) -> MemoryRelation:
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                relation = MemoryRelation(
                    scope=scope,
                    scope_id=scope_id,
                    subject_key=subject_key,
                    predicate=predicate,
                    object_text=object_text,
                    confidence=confidence,
                    evidence_count=evidence_count,
                    status=status,
                    valid_at=valid_at,
                    invalid_at=invalid_at,
                    superseded_by=superseded_by,
                    memory_id=memory_id,
                    memory_type=memory_type,
                )
                session.add(relation)
                await session.flush()
                await session.refresh(relation)
                return relation

    async def get_relation_by_id(self, relation_id: str) -> MemoryRelation | None:
        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryRelation).where(MemoryRelation.relation_id == relation_id)
            )
            return result.scalar_one_or_none()

    async def get_active_relation_by_signature(
        self,
        scope: str,
        scope_id: str,
        subject_key: str,
        predicate: str,
        object_text: str,
        *,
        now: datetime | None = None,
    ) -> MemoryRelation | None:
        target_time = now or datetime.now(timezone.utc)
        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryRelation)
                .where(
                    MemoryRelation.scope == scope,
                    MemoryRelation.scope_id == scope_id,
                    MemoryRelation.subject_key == subject_key,
                    MemoryRelation.predicate == predicate,
                    MemoryRelation.object_text == object_text,
                    MemoryRelation.status == "active",
                    or_(
                        MemoryRelation.valid_at.is_(None),
                        MemoryRelation.valid_at <= target_time,
                    ),
                    or_(
                        MemoryRelation.invalid_at.is_(None),
                        MemoryRelation.invalid_at > target_time,
                    ),
                )
                .order_by(desc(MemoryRelation.updated_at))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def update_relation(
        self,
        relation_id: str,
        *,
        confidence: float | None = None,
        evidence_count: int | None = None,
        status: str | None = None,
        valid_at: datetime | None = object,  # type: ignore[assignment]
        invalid_at: datetime | None = object,  # type: ignore[assignment]
        superseded_by: str | None = object,  # type: ignore[assignment]
        memory_id: str | None = object,  # type: ignore[assignment]
        memory_type: str | None = object,  # type: ignore[assignment]
    ) -> MemoryRelation | None:
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                values: dict = {}
                if confidence is not None:
                    values["confidence"] = confidence
                if evidence_count is not None:
                    values["evidence_count"] = evidence_count
                if status is not None:
                    values["status"] = status
                if valid_at is not object:
                    values["valid_at"] = valid_at
                if invalid_at is not object:
                    values["invalid_at"] = invalid_at
                if superseded_by is not object:
                    values["superseded_by"] = superseded_by
                if memory_id is not object:
                    values["memory_id"] = memory_id
                if memory_type is not object:
                    values["memory_type"] = memory_type
                if not values:
                    return await self.get_relation_by_id(relation_id)
                values["updated_at"] = datetime.now(timezone.utc)
                await session.execute(
                    update(MemoryRelation)
                    .where(MemoryRelation.relation_id == relation_id)
                    .values(**values)
                )
        return await self.get_relation_by_id(relation_id)

    async def supersede_conflicting_relations(
        self,
        *,
        scope: str,
        scope_id: str,
        subject_key: str,
        predicate: str,
        keep_relation_id: str,
        object_text: str,
        at_time: datetime | None = None,
    ) -> int:
        """Supersede active relations with same (subject, predicate) and different object."""
        ts = at_time or datetime.now(timezone.utc)
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                result = await session.execute(
                    update(MemoryRelation)
                    .where(
                        MemoryRelation.scope == scope,
                        MemoryRelation.scope_id == scope_id,
                        MemoryRelation.subject_key == subject_key,
                        MemoryRelation.predicate == predicate,
                        MemoryRelation.status == "active",
                        MemoryRelation.relation_id != keep_relation_id,
                        MemoryRelation.object_text != object_text,
                    )
                    .values(
                        status="superseded",
                        invalid_at=ts,
                        superseded_by=keep_relation_id,
                        updated_at=ts,
                    )
                )
                return int(result.rowcount or 0)

    async def upsert_relation(
        self,
        *,
        scope: str,
        scope_id: str,
        subject_key: str,
        predicate: str,
        object_text: str,
        confidence: float,
        evidence_count: int,
        memory_id: str | None = None,
        memory_type: str | None = None,
        now: datetime | None = None,
    ) -> MemoryRelation | None:
        """Create or refresh relation and supersede conflicting active variants."""
        if not scope or not scope_id or not subject_key or not predicate or not object_text:
            return None

        ts = now or datetime.now(timezone.utc)
        existing = await self.get_active_relation_by_signature(
            scope=scope,
            scope_id=scope_id,
            subject_key=subject_key,
            predicate=predicate,
            object_text=object_text,
            now=ts,
        )
        if existing:
            update_kwargs: dict = {}
            if memory_id is not None:
                update_kwargs["memory_id"] = memory_id
            if memory_type is not None:
                update_kwargs["memory_type"] = memory_type
            relation = await self.update_relation(
                existing.relation_id,
                confidence=max(float(existing.confidence), float(confidence)),
                evidence_count=max(int(existing.evidence_count), int(evidence_count)),
                **update_kwargs,
            )
        else:
            relation = await self.insert_relation(
                scope=scope,
                scope_id=scope_id,
                subject_key=subject_key,
                predicate=predicate,
                object_text=object_text,
                confidence=confidence,
                evidence_count=evidence_count,
                status="active",
                valid_at=ts,
                memory_id=memory_id,
                memory_type=memory_type,
            )

        if relation is None:
            return None

        await self.supersede_conflicting_relations(
            scope=scope,
            scope_id=scope_id,
            subject_key=subject_key,
            predicate=predicate,
            keep_relation_id=relation.relation_id,
            object_text=object_text,
            at_time=ts,
        )
        return relation

    async def get_active_relations_for_scope(
        self,
        scope: str,
        scope_id: str,
        min_confidence: float = 0.0,
        limit: int = 100,
        as_of: datetime | None = None,
    ) -> list[MemoryRelation]:
        target_time = as_of or datetime.now(timezone.utc)
        status_filter = (
            MemoryRelation.status.in_(["active", "superseded"])
            if as_of is not None
            else MemoryRelation.status == "active"
        )
        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryRelation)
                .where(
                    MemoryRelation.scope == scope,
                    MemoryRelation.scope_id == scope_id,
                    status_filter,
                    MemoryRelation.confidence >= min_confidence,
                    or_(
                        MemoryRelation.valid_at.is_(None),
                        MemoryRelation.valid_at <= target_time,
                    ),
                    or_(
                        MemoryRelation.invalid_at.is_(None),
                        MemoryRelation.invalid_at > target_time,
                    ),
                )
                .order_by(
                    desc(MemoryRelation.confidence),
                    desc(MemoryRelation.updated_at),
                )
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_active_relations_for_scopes(
        self,
        scopes: list[tuple[str, str]],
        min_confidence: float = 0.0,
        limit: int = 300,
        as_of: datetime | None = None,
    ) -> list[MemoryRelation]:
        normalized_scopes: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for entry in scopes:
            if not isinstance(entry, tuple) or len(entry) != 2:
                continue
            scope, scope_id = str(entry[0]).strip(), str(entry[1]).strip()
            if not scope or not scope_id:
                continue
            key = (scope, scope_id)
            if key not in seen:
                seen.add(key)
                normalized_scopes.append(key)

        if not normalized_scopes:
            return []

        conditions = [
            and_(
                MemoryRelation.scope == scope,
                MemoryRelation.scope_id == scope_id,
            )
            for scope, scope_id in normalized_scopes
        ]
        target_time = as_of or datetime.now(timezone.utc)
        status_filter = (
            MemoryRelation.status.in_(["active", "superseded"])
            if as_of is not None
            else MemoryRelation.status == "active"
        )

        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryRelation)
                .where(
                    or_(*conditions),
                    status_filter,
                    MemoryRelation.confidence >= min_confidence,
                    or_(
                        MemoryRelation.valid_at.is_(None),
                        MemoryRelation.valid_at <= target_time,
                    ),
                    or_(
                        MemoryRelation.invalid_at.is_(None),
                        MemoryRelation.invalid_at > target_time,
                    ),
                )
                .order_by(
                    desc(MemoryRelation.confidence),
                    desc(MemoryRelation.updated_at),
                )
                .limit(limit)
            )
            return list(result.scalars().all())

    async def list_relations(
        self,
        scope: str | None = None,
        scope_id: str | None = None,
        predicate: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[MemoryRelation], int]:
        async with self._db.get_db() as session:
            session: AsyncSession
            query = select(MemoryRelation)
            count_base = select(func.count()).select_from(MemoryRelation)

            filters = []
            if scope:
                filters.append(MemoryRelation.scope == scope)
            if scope_id:
                filters.append(MemoryRelation.scope_id == scope_id)
            if predicate:
                filters.append(MemoryRelation.predicate == predicate)
            if status:
                filters.append(MemoryRelation.status == status)

            for f in filters:
                query = query.where(f)
                count_base = count_base.where(f)

            total = (await session.execute(count_base)).scalar_one()
            offset = (page - 1) * page_size
            result = await session.execute(
                query.order_by(desc(MemoryRelation.updated_at))
                .offset(offset)
                .limit(page_size)
            )
            return list(result.scalars().all()), total

    async def delete_relation(self, relation_id: str) -> None:
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                await session.execute(
                    delete(MemoryRelation).where(
                        MemoryRelation.relation_id == relation_id
                    )
                )

    # ------------------------------------------------------------------ #
    #  Maintenance / Cleanup
    # ------------------------------------------------------------------ #

    async def delete_processed_events(
        self, older_than_days: int = 7
    ) -> int:
        """Delete processed events older than *older_than_days*.

        Returns the number of deleted rows.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                result = await session.execute(
                    delete(MemoryEvent).where(
                        MemoryEvent.processed == True,  # noqa: E712
                        col(MemoryEvent.created_at) < cutoff,
                    )
                )
                return result.rowcount  # type: ignore[return-value]

    async def prune_orphan_evidence(self) -> int:
        """Delete evidence rows whose memory_id no longer exists.

        Returns the number of pruned rows.
        """
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                # Sub-query: all existing memory_ids
                existing_ids = select(MemoryItem.memory_id)
                result = await session.execute(
                    delete(MemoryEvidence).where(
                        ~col(MemoryEvidence.memory_id).in_(existing_ids)
                    )
                )
                return result.rowcount  # type: ignore[return-value]

    async def get_eviction_candidates(
        self,
        scope: str,
        scope_id: str,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Return the lowest-priority active/shadow items for eviction.

        Priority score = importance * 0.4 + confidence * 0.3 + recency * 0.3
        (recency approximated by updated_at ASC — oldest = lowest).
        """
        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryItem)
                .where(
                    MemoryItem.scope == scope,
                    MemoryItem.scope_id == scope_id,
                    MemoryItem.status.in_(["active", "shadow"]),
                )
                .order_by(
                    # Lowest composite score first (importance + confidence
                    # weighted, then oldest updated_at as tiebreaker)
                    (MemoryItem.importance * 0.4 + MemoryItem.confidence * 0.3),
                    MemoryItem.updated_at,
                )
                .limit(limit)
            )
            return list(result.scalars().all())

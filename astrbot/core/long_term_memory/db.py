"""Database operations for the Long-Term Memory system.

Provides async CRUD for MemoryEvent, MemoryItem, and MemoryEvidence tables.
Designed to be used by LTMManager and the dashboard API.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, desc, func, select, update

from astrbot.core.db import BaseDatabase

from .models import MemoryEvent, MemoryEvidence, MemoryItem


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
        self, limit: int = 50
    ) -> list[MemoryEvent]:
        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryEvent)
                .where(MemoryEvent.processed == False)  # noqa: E712
                .order_by(MemoryEvent.created_at)
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
                    .values(processed=True)
                )

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
        confidence: float = 0.5,
        importance: float = 0.5,
        evidence_count: int = 1,
        ttl_days: int | None = None,
        status: str = "shadow",
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
                    confidence=confidence,
                    importance=importance,
                    evidence_count=evidence_count,
                    ttl_days=ttl_days,
                    status=status,
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
    ) -> list[MemoryItem]:
        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryItem)
                .where(
                    MemoryItem.scope == scope,
                    MemoryItem.scope_id == scope_id,
                    MemoryItem.status == "active",
                    MemoryItem.confidence >= min_confidence,
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

        async with self._db.get_db() as session:
            session: AsyncSession
            result = await session.execute(
                select(MemoryItem)
                .where(
                    or_(*conditions),
                    MemoryItem.status == "active",
                    MemoryItem.confidence >= min_confidence,
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
        confidence: float | None = None,
        importance: float | None = None,
        evidence_count: int | None = None,
        status: str | None = None,
        ttl_days: int | None = object,  # type: ignore[assignment]
    ) -> MemoryItem | None:
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                values: dict = {}
                if fact is not None:
                    values["fact"] = fact
                if confidence is not None:
                    values["confidence"] = confidence
                if importance is not None:
                    values["importance"] = importance
                if evidence_count is not None:
                    values["evidence_count"] = evidence_count
                if status is not None:
                    values["status"] = status
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

    async def expire_old_items(self) -> int:
        """Mark items past their TTL as expired. Returns count of expired items."""
        now = datetime.now(timezone.utc)
        async with self._db.get_db() as session:
            session: AsyncSession
            async with session.begin():
                # Find items that have TTL and are past expiry
                items = await session.execute(
                    select(MemoryItem).where(
                        MemoryItem.ttl_days.isnot(None),
                        MemoryItem.status.in_(["active", "shadow"]),
                    )
                )
                expired_count = 0
                for item in items.scalars().all():
                    if item.ttl_days and item.ttl_days > 0:
                        created = item.created_at
                        if created.tzinfo is None:
                            created = created.replace(tzinfo=timezone.utc)
                        expiry = created + timedelta(days=item.ttl_days)
                        if now > expiry:
                            item.status = "expired"
                            expired_count += 1
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

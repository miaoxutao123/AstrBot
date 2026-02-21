"""LTMManager — central coordinator for the Long-Term Memory system.

Provides a high-level API for the rest of AstrBot to:
- Record events from conversations and tool calls
- Retrieve memory context for prompt injection
- Run background maintenance tasks (extraction, expiration)
"""

import asyncio
from typing import Any

from astrbot import logger
from astrbot.core.db import BaseDatabase
from astrbot.core.provider.provider import Provider

from .db import MemoryDB
from .policy import DEFAULT_RETENTION_DAYS, MemoryMaintenancePolicy, MemoryReadPolicy, MemoryWritePolicy
from .reader import MemoryReader
from .writer import MemoryWriter


class LTMManager:
    """Central coordinator for the Long-Term Memory system."""

    def __init__(self, db: BaseDatabase) -> None:
        self._memory_db = MemoryDB(db)
        self._writer = MemoryWriter(self._memory_db)
        self._reader = MemoryReader(self._memory_db)
        self._initialized = False
        self._extraction_task: asyncio.Task | None = None
        self._extraction_pending = False
        self._pending_extraction_args: (
            tuple[Provider, MemoryWritePolicy | None, dict[str, int] | None] | None
        ) = None

    @property
    def memory_db(self) -> MemoryDB:
        return self._memory_db

    # ------------------------------------------------------------------ #
    #  Event Recording (called from hooks)
    # ------------------------------------------------------------------ #

    async def record_conversation_event(
        self,
        scope: str,
        scope_id: str,
        role: str,
        text: str,
        platform_id: str | None = None,
        session_id: str | None = None,
    ) -> str | None:
        """Record a conversation message as a memory event.

        Returns the event_id, or None if recording is skipped.
        """
        if not text or not text.strip():
            return None

        try:
            return await self._writer.record_event(
                scope=scope,
                scope_id=scope_id,
                source_type="message",
                source_role=role,
                content={"text": text.strip()},
                platform_id=platform_id,
                session_id=session_id,
            )
        except Exception as e:
            logger.debug("LTM event recording failed: %s", e)
            return None

    async def record_tool_event(
        self,
        scope: str,
        scope_id: str,
        tool_name: str,
        tool_args: dict | None,
        tool_result: str | None,
        platform_id: str | None = None,
        session_id: str | None = None,
    ) -> str | None:
        """Record a tool execution as a memory event."""
        content: dict[str, Any] = {"tool_name": tool_name}
        if tool_args:
            # Only record a summary of args, not full payloads
            content["args_summary"] = str(tool_args)[:200]
        if tool_result:
            content["result_summary"] = str(tool_result)[:500]

        try:
            return await self._writer.record_event(
                scope=scope,
                scope_id=scope_id,
                source_type="tool_result",
                source_role="tool",
                content=content,
                platform_id=platform_id,
                session_id=session_id,
            )
        except Exception as e:
            logger.debug("LTM tool event recording failed: %s", e)
            return None

    # ------------------------------------------------------------------ #
    #  Memory Retrieval (called before LLM requests)
    # ------------------------------------------------------------------ #

    async def retrieve_memory_context(
        self,
        scope: str,
        scope_id: str,
        read_policy: MemoryReadPolicy | None = None,
        query_text: str | None = None,
        additional_scopes: list[tuple[str, str]] | None = None,
    ) -> str:
        """Retrieve formatted memory context for prompt injection.

        Returns a formatted string block, or empty string if nothing relevant.
        """
        policy = read_policy or MemoryReadPolicy()
        try:
            return await self._reader.retrieve_memory_context(
                scope=scope,
                scope_id=scope_id,
                read_policy=policy,
                query_text=query_text,
                additional_scopes=additional_scopes,
            )
        except Exception as e:
            logger.warning("LTM retrieval failed: %s", e)
            return ""

    # ------------------------------------------------------------------ #
    #  Background Processing
    # ------------------------------------------------------------------ #

    async def run_extraction_cycle(
        self,
        provider: Provider,
        write_policy: MemoryWritePolicy | None = None,
        retention_days: dict[str, int] | None = None,
    ) -> int:
        """Run one cycle of background extraction.

        Processes unprocessed events, extracts candidates, and persists
        memory items according to the write policy.

        Returns the number of items created/updated.
        """
        policy = write_policy or MemoryWritePolicy()
        retention = retention_days or DEFAULT_RETENTION_DAYS
        return await self._writer.process_pending_events(
            provider=provider,
            write_policy=policy,
            retention_days=retention,
        )

    async def run_expiration_sweep(self) -> int:
        """Expire items past their TTL. Returns count of expired items."""
        try:
            return await self._memory_db.expire_old_items()
        except Exception as e:
            logger.warning("LTM expiration sweep failed: %s", e)
            return 0

    async def run_maintenance_sweep(
        self,
        maintenance_policy: MemoryMaintenancePolicy | None = None,
    ) -> dict:
        """Run all hygiene tasks in one sweep.

        Returns a summary dict with counts for each operation.
        """
        policy = maintenance_policy or MemoryMaintenancePolicy()
        result: dict[str, int] = {
            "expired": 0,
            "events_cleaned": 0,
            "evidence_pruned": 0,
        }
        try:
            result["expired"] = await self._memory_db.expire_old_items()
        except Exception as e:
            logger.warning("LTM maintenance: expire_old_items failed: %s", e)
        try:
            result["events_cleaned"] = await self._memory_db.delete_processed_events(
                older_than_days=policy.event_retention_days,
            )
        except Exception as e:
            logger.warning("LTM maintenance: delete_processed_events failed: %s", e)
        try:
            result["evidence_pruned"] = await self._memory_db.prune_orphan_evidence()
        except Exception as e:
            logger.warning("LTM maintenance: prune_orphan_evidence failed: %s", e)

        total = sum(result.values())
        if total > 0:
            logger.info("LTM maintenance sweep: %s", result)
        return result

    async def register_cron_jobs(
        self,
        cron_manager,
        maintenance_policy: MemoryMaintenancePolicy | None = None,
        write_policy: MemoryWritePolicy | None = None,
        provider: Provider | None = None,
    ) -> None:
        """Register LTM maintenance cron jobs with the CronJobManager."""
        policy = maintenance_policy or MemoryMaintenancePolicy()

        # Maintenance sweep (expiration + event cleanup + evidence pruning)
        await cron_manager.add_basic_job(
            name="ltm_maintenance_sweep",
            cron_expression=policy.maintenance_cron,
            handler=lambda: asyncio.ensure_future(
                self.run_maintenance_sweep(policy)
            ),
            description="LTM: expire items, clean events, prune evidence",
            persistent=False,
        )
        logger.info(
            "LTM cron registered: maintenance_sweep @ %s",
            policy.maintenance_cron,
        )

        # Consolidation (optional, requires provider)
        if policy.enable_consolidation and provider is not None:
            await cron_manager.add_basic_job(
                name="ltm_consolidation",
                cron_expression=policy.consolidation_cron,
                handler=lambda: asyncio.ensure_future(
                    self.run_consolidation(provider=provider)
                ),
                description="LTM: consolidate similar memories",
                persistent=False,
            )
            logger.info(
                "LTM cron registered: consolidation @ %s",
                policy.consolidation_cron,
            )

    async def run_consolidation(
        self,
        provider: Provider,
        scope: str | None = None,
        scope_id: str | None = None,
    ) -> int:
        """Run memory consolidation. Returns count of consolidated items."""
        try:
            from .consolidator import MemoryConsolidator

            consolidator = MemoryConsolidator(self._memory_db)
            return await consolidator.run_consolidation(
                provider=provider,
                scope=scope,
                scope_id=scope_id,
            )
        except Exception as e:
            logger.warning("LTM consolidation failed: %s", e)
            return 0

    def schedule_extraction(
        self,
        provider: Provider,
        write_policy: MemoryWritePolicy | None = None,
        retention_days: dict[str, int] | None = None,
    ) -> None:
        """Schedule an async extraction cycle (fire-and-forget).

        Safe to call from the hot path — extraction runs in background.
        """
        self._pending_extraction_args = (provider, write_policy, retention_days)
        self._extraction_pending = True
        if self._extraction_task and not self._extraction_task.done():
            # A cycle is already running. Keep the pending flag so it will
            # immediately run one more cycle after current one completes.
            return

        async def _run():
            while self._extraction_pending:
                self._extraction_pending = False
                pending = self._pending_extraction_args
                if pending is None:
                    break
                _provider, _write_policy, _retention_days = pending
                try:
                    count = await self.run_extraction_cycle(
                        provider=_provider,
                        write_policy=_write_policy,
                        retention_days=_retention_days,
                    )
                    if count > 0:
                        logger.info(
                            "LTM extraction cycle: %d items created/updated",
                            count,
                        )
                except Exception as e:
                    logger.warning("LTM background extraction failed: %s", e)

        self._extraction_task = asyncio.create_task(_run())

    # ------------------------------------------------------------------ #
    #  Session Lifecycle
    # ------------------------------------------------------------------ #

    def on_session_end(self) -> None:
        """Called when a session ends to reset per-session counters."""
        self._writer.reset_session_counts()


# Module-level singleton — initialized lazily by the core lifecycle.
_ltm_manager: LTMManager | None = None


def get_ltm_manager() -> LTMManager | None:
    """Get the global LTMManager instance, or None if not initialized."""
    return _ltm_manager


def init_ltm_manager(db: BaseDatabase) -> LTMManager:
    """Initialize the global LTMManager instance."""
    global _ltm_manager
    _ltm_manager = LTMManager(db)
    return _ltm_manager

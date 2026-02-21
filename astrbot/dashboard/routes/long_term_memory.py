"""Dashboard API routes for Long-Term Memory management."""

import traceback

from quart import request

from astrbot.core import logger
from astrbot.core.db import BaseDatabase

from .route import Response, Route, RouteContext


class LongTermMemoryRoute(Route):
    def __init__(
        self,
        context: RouteContext,
        db_helper: BaseDatabase,
    ) -> None:
        super().__init__(context)
        self.db_helper = db_helper
        self.routes = {
            "/ltm/items": [
                ("GET", self.list_items),
            ],
            "/ltm/items/<memory_id>": [
                ("GET", self.get_item),
                ("PATCH", self.update_item),
                ("DELETE", self.delete_item),
            ],
            "/ltm/events": ("GET", self.list_events),
            "/ltm/stats": ("GET", self.get_stats),
        }
        self.register_routes()

    def _get_memory_db(self):
        from astrbot.core.long_term_memory.db import MemoryDB

        return MemoryDB(self.db_helper)

    async def list_items(self):
        try:
            memory_db = self._get_memory_db()
            page = int(request.args.get("page", 1))
            page_size = int(request.args.get("page_size", 20))
            scope = request.args.get("scope")
            scope_id = request.args.get("scope_id")
            mem_type = request.args.get("type")
            status = request.args.get("status")
            min_confidence = float(request.args.get("min_confidence", 0))

            items, total = await memory_db.list_items(
                scope=scope,
                scope_id=scope_id,
                type=mem_type,
                status=status,
                min_confidence=min_confidence,
                page=page,
                page_size=page_size,
            )

            return Response().ok({
                "items": [
                    {
                        "memory_id": item.memory_id,
                        "scope": item.scope,
                        "scope_id": item.scope_id,
                        "type": item.type,
                        "fact": item.fact,
                        "fact_key": item.fact_key,
                        "confidence": item.confidence,
                        "importance": item.importance,
                        "evidence_count": item.evidence_count,
                        "ttl_days": item.ttl_days,
                        "status": item.status,
                        "consolidation_count": item.consolidation_count,
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                    }
                    for item in items
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            }).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def get_item(self, memory_id: str):
        try:
            memory_db = self._get_memory_db()
            item = await memory_db.get_item_by_id(memory_id)
            if not item:
                return Response().error("Memory item not found").__dict__

            evidence = await memory_db.get_evidence_for_item(memory_id)

            return Response().ok({
                "item": {
                    "memory_id": item.memory_id,
                    "scope": item.scope,
                    "scope_id": item.scope_id,
                    "type": item.type,
                    "fact": item.fact,
                    "fact_key": item.fact_key,
                    "confidence": item.confidence,
                    "importance": item.importance,
                    "evidence_count": item.evidence_count,
                    "ttl_days": item.ttl_days,
                    "status": item.status,
                    "consolidation_count": item.consolidation_count,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                },
                "evidence": [
                    {
                        "id": ev.id,
                        "event_id": ev.event_id,
                        "extraction_method": ev.extraction_method,
                        "extraction_meta": ev.extraction_meta,
                    }
                    for ev in evidence
                ],
            }).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def update_item(self, memory_id: str):
        try:
            memory_db = self._get_memory_db()
            data = await request.get_json()

            kwargs = {}
            if "status" in data:
                if data["status"] not in ("active", "shadow", "disabled", "expired", "consolidated"):
                    return Response().error("Invalid status").__dict__
                kwargs["status"] = data["status"]
            if "importance" in data:
                kwargs["importance"] = max(0.0, min(1.0, float(data["importance"])))
            if "ttl_days" in data:
                kwargs["ttl_days"] = int(data["ttl_days"]) if data["ttl_days"] is not None else None
            if "fact" in data:
                kwargs["fact"] = str(data["fact"])

            if not kwargs:
                return Response().error("No fields to update").__dict__

            item = await memory_db.update_item(memory_id, **kwargs)
            if not item:
                return Response().error("Memory item not found").__dict__

            return Response().ok({
                "memory_id": item.memory_id,
                "status": item.status,
                "importance": item.importance,
                "ttl_days": item.ttl_days,
            }).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def delete_item(self, memory_id: str):
        try:
            memory_db = self._get_memory_db()
            item = await memory_db.get_item_by_id(memory_id)
            if not item:
                return Response().error("Memory item not found").__dict__

            await memory_db.delete_item(memory_id)
            return Response().ok(message="Memory item deleted").__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def list_events(self):
        try:
            memory_db = self._get_memory_db()
            page = int(request.args.get("page", 1))
            page_size = int(request.args.get("page_size", 20))
            scope = request.args.get("scope")
            scope_id = request.args.get("scope_id")

            events, total = await memory_db.list_events(
                scope=scope,
                scope_id=scope_id,
                page=page,
                page_size=page_size,
            )

            return Response().ok({
                "events": [
                    {
                        "event_id": ev.event_id,
                        "scope": ev.scope,
                        "scope_id": ev.scope_id,
                        "source_type": ev.source_type,
                        "source_role": ev.source_role,
                        "content": ev.content,
                        "platform_id": ev.platform_id,
                        "session_id": ev.session_id,
                        "processed": ev.processed,
                        "created_at": ev.created_at.isoformat() if ev.created_at else None,
                    }
                    for ev in events
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            }).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def get_stats(self):
        try:
            memory_db = self._get_memory_db()
            scope = request.args.get("scope")
            scope_id = request.args.get("scope_id")

            stats = await memory_db.get_stats(scope=scope, scope_id=scope_id)
            return Response().ok(stats).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

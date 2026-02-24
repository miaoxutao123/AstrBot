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
            "/ltm/relations": [
                ("GET", self.list_relations),
            ],
            "/ltm/relations/<relation_id>": [
                ("GET", self.get_relation),
                ("PATCH", self.update_relation),
                ("DELETE", self.delete_relation),
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
                if data["status"] not in (
                    "active",
                    "shadow",
                    "disabled",
                    "expired",
                    "consolidated",
                    "superseded",
                ):
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

    async def list_relations(self):
        try:
            memory_db = self._get_memory_db()
            page = int(request.args.get("page", 1))
            page_size = int(request.args.get("page_size", 20))
            scope = request.args.get("scope")
            scope_id = request.args.get("scope_id")
            predicate = request.args.get("predicate")
            status = request.args.get("status")

            relations, total = await memory_db.list_relations(
                scope=scope,
                scope_id=scope_id,
                predicate=predicate,
                status=status,
                page=page,
                page_size=page_size,
            )

            return Response().ok({
                "relations": [
                    {
                        "relation_id": rel.relation_id,
                        "scope": rel.scope,
                        "scope_id": rel.scope_id,
                        "subject_key": rel.subject_key,
                        "predicate": rel.predicate,
                        "object_text": rel.object_text,
                        "confidence": rel.confidence,
                        "evidence_count": rel.evidence_count,
                        "status": rel.status,
                        "valid_at": rel.valid_at.isoformat() if rel.valid_at else None,
                        "invalid_at": rel.invalid_at.isoformat() if rel.invalid_at else None,
                        "superseded_by": rel.superseded_by,
                        "memory_id": rel.memory_id,
                        "memory_type": rel.memory_type,
                        "created_at": rel.created_at.isoformat() if rel.created_at else None,
                        "updated_at": rel.updated_at.isoformat() if rel.updated_at else None,
                    }
                    for rel in relations
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            }).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def get_relation(self, relation_id: str):
        try:
            memory_db = self._get_memory_db()
            relation = await memory_db.get_relation_by_id(relation_id)
            if not relation:
                return Response().error("Memory relation not found").__dict__

            return Response().ok({
                "relation": {
                    "relation_id": relation.relation_id,
                    "scope": relation.scope,
                    "scope_id": relation.scope_id,
                    "subject_key": relation.subject_key,
                    "predicate": relation.predicate,
                    "object_text": relation.object_text,
                    "confidence": relation.confidence,
                    "evidence_count": relation.evidence_count,
                    "status": relation.status,
                    "valid_at": relation.valid_at.isoformat() if relation.valid_at else None,
                    "invalid_at": relation.invalid_at.isoformat() if relation.invalid_at else None,
                    "superseded_by": relation.superseded_by,
                    "memory_id": relation.memory_id,
                    "memory_type": relation.memory_type,
                    "created_at": relation.created_at.isoformat() if relation.created_at else None,
                    "updated_at": relation.updated_at.isoformat() if relation.updated_at else None,
                }
            }).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def update_relation(self, relation_id: str):
        try:
            memory_db = self._get_memory_db()
            data = await request.get_json()

            kwargs = {}
            if "status" in data:
                if data["status"] not in ("active", "superseded", "disabled"):
                    return Response().error("Invalid relation status").__dict__
                kwargs["status"] = data["status"]
            if "confidence" in data:
                kwargs["confidence"] = max(0.0, min(1.0, float(data["confidence"])))
            if "evidence_count" in data:
                kwargs["evidence_count"] = max(1, int(data["evidence_count"]))

            if not kwargs:
                return Response().error("No fields to update").__dict__

            relation = await memory_db.update_relation(relation_id, **kwargs)
            if not relation:
                return Response().error("Memory relation not found").__dict__

            return Response().ok({
                "relation_id": relation.relation_id,
                "status": relation.status,
                "confidence": relation.confidence,
                "evidence_count": relation.evidence_count,
            }).__dict__
        except Exception as e:
            logger.error(traceback.format_exc())
            return Response().error(str(e)).__dict__

    async def delete_relation(self, relation_id: str):
        try:
            memory_db = self._get_memory_db()
            relation = await memory_db.get_relation_by_id(relation_id)
            if not relation:
                return Response().error("Memory relation not found").__dict__

            await memory_db.delete_relation(relation_id)
            return Response().ok(message="Memory relation deleted").__dict__
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

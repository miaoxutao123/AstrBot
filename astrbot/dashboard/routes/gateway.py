"""Dashboard routes for Gateway (Long Poll, WebSocket, config)."""

import hashlib
from quart import g, request, websocket

from astrbot.core import logger
from astrbot.core.gateway import LongPollQueue, GatewayWebSocketHandler
from astrbot.core.db import BaseDatabase
from astrbot.core.core_lifecycle import AstrBotCoreLifecycle
from astrbot.dashboard.routes.api_key import ALL_OPEN_API_SCOPES
from .route import Response, Route, RouteContext


class GatewayRoute(Route):
    """Provides REST + WS endpoints for the Unified Gateway."""

    def __init__(
        self,
        context: RouteContext,
        db: BaseDatabase,
        core_lifecycle: AstrBotCoreLifecycle,
    ) -> None:
        super().__init__(context)
        self.db = db
        self.core_lifecycle = core_lifecycle
        self.dispatcher = getattr(
            core_lifecycle.pipeline_scheduler_mapping.get("default", None),
            "ctx",
            None,
        )
        self.dispatcher = getattr(self.dispatcher, "gateway_dispatcher", None)
        self.routes = {
            "/gateway/events": ("GET", self.get_events),
            "/gateway/events/ack": ("POST", self.ack_events),
        }
        self.register_routes()
        self.app.websocket("/api/gateway/stream")(self.gateway_ws)

    def _get_dispatcher(self):
        """Lazily resolve the gateway dispatcher from the pipeline context."""
        scheduler = self.core_lifecycle.pipeline_scheduler_mapping.get("default")
        if scheduler is None:
            return None
        ctx = getattr(scheduler, "ctx", None)
        if ctx is None:
            return None
        return getattr(ctx, "gateway_dispatcher", None)

    async def _resolve_api_key(self) -> tuple[str | None, str | None]:
        raw_key = None
        if key := request.args.get("api_key"):
            raw_key = key.strip()
        elif key := request.headers.get("X-API-Key"):
            raw_key = key.strip()
        else:
            auth = request.headers.get("Authorization", "").strip()
            if auth.startswith("Bearer "):
                raw_key = auth.removeprefix("Bearer ").strip()
        if not raw_key:
            return None, "Missing API key"
        key_hash = hashlib.pbkdf2_hmac(
            "sha256", raw_key.encode("utf-8"), b"astrbot_api_key", 100_000
        ).hex()
        api_key = await self.db.get_active_api_key_by_hash(key_hash)
        if not api_key:
            return None, "Invalid API key"
        return api_key.key_id, None

    async def get_events(self):
        key_id, err = await self._resolve_api_key()
        if err:
            return Response().error(err).__dict__
        dispatcher = self._get_dispatcher()
        if not dispatcher:
            return Response().error("Gateway not enabled").__dict__
        timeout = float(request.args.get("timeout", 30))
        platform = request.args.get("platform")
        events = await dispatcher.longpoll.dequeue(key_id, timeout)
        if platform:
            events = [e for e in events if e.get("platform", {}).get("name") == platform]
        return Response().ok(data={"events": events}).__dict__

    async def ack_events(self):
        key_id, err = await self._resolve_api_key()
        if err:
            return Response().error(err).__dict__
        post_data = await request.json or {}
        event_ids = post_data.get("event_ids", [])
        dispatcher = self._get_dispatcher()
        if dispatcher:
            dispatcher.longpoll.ack(key_id, event_ids)
        return Response().ok().__dict__

    async def gateway_ws(self):
        # API key auth via query/header
        raw_key = None
        if key := websocket.args.get("api_key"):
            raw_key = key.strip()
        elif key := websocket.headers.get("X-API-Key"):
            raw_key = key.strip()
        else:
            auth = websocket.headers.get("Authorization", "").strip()
            if auth.startswith("Bearer "):
                raw_key = auth.removeprefix("Bearer ").strip()
        if not raw_key:
            await websocket.close(1008, "Missing API key")
            return
        key_hash = hashlib.pbkdf2_hmac(
            "sha256", raw_key.encode("utf-8"), b"astrbot_api_key", 100_000
        ).hex()
        api_key = await self.db.get_active_api_key_by_hash(key_hash)
        if not api_key:
            await websocket.close(1008, "Invalid API key")
            return
        key_id = api_key.key_id
        dispatcher = self._get_dispatcher()
        if not dispatcher:
            await websocket.close(1011, "Gateway not enabled")
            return

        ws_handler = dispatcher.ws_handler
        if not ws_handler.register(key_id, websocket):
            await websocket.close(1008, "Max connections reached")
            return

        try:
            while True:
                msg = await websocket.receive_json()
                op = msg.get("op")
                if op == "ping":
                    await websocket.send_json({"op": "pong"})
                elif op == "send_message":
                    result = await ws_handler.handle_send_message(
                        msg.get("data", {}), self.core_lifecycle.platform_manager
                    )
                    await websocket.send_json({"op": "send_message_result", "data": result})
                elif op == "subscribe":
                    await websocket.send_json({"op": "subscribed", "data": msg.get("filters")})
        except Exception as e:
            logger.debug(f"Gateway WS closed for {key_id}: {e}")
        finally:
            ws_handler.unregister(key_id, websocket)

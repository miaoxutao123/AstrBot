"""WebSocket server handler for full-duplex Agent connections."""

import asyncio
from astrbot.core import logger
from .envelope import MessageEnvelope


class GatewayWebSocketHandler:
    def __init__(self, config: dict):
        self.enabled = config.get("enabled", False)
        self.max_conn_per_key = config.get("max_connections_per_key", 3)
        self.heartbeat_interval = config.get("heartbeat_interval_seconds", 30)
        self._connections: dict[str, list] = {}

    async def initialize(self):
        pass

    def register(self, key_id: str, websocket):
        conns = self._connections.setdefault(key_id, [])
        if len(conns) >= self.max_conn_per_key:
            return False
        conns.append(websocket)
        return True

    def unregister(self, key_id: str, websocket):
        conns = self._connections.get(key_id, [])
        if websocket in conns:
            conns.remove(websocket)

    async def broadcast(self, envelope: MessageEnvelope):
        payload = {"op": "event", "data": envelope.to_dict()}
        dead = []
        for key_id, conns in list(self._connections.items()):
            for ws in conns:
                try:
                    await ws.send_json(payload)
                except Exception:
                    dead.append((key_id, ws))
        for key_id, ws in dead:
            self.unregister(key_id, ws)

    async def handle_send_message(self, data: dict, platform_manager) -> dict:
        """Handle Agent -> AstraBot send_message via WS."""
        umo = data.get("umo")
        message_payload = data.get("message")
        if not umo or not message_payload:
            return {"success": False, "error": "Missing umo or message"}
        from astrbot.core.platform.message_session import MessageSesion
        from astrbot.core.platform.sources.webchat.message_parts_helper import build_message_chain_from_payload
        try:
            session = MessageSesion.from_str(str(umo))
        except Exception as e:
            return {"success": False, "error": f"Invalid umo: {e}"}
        platform_inst = next(
            (inst for inst in platform_manager.platform_insts if inst.meta().id == session.platform_name),
            None,
        )
        if not platform_inst:
            return {"success": False, "error": f"Platform not found: {session.platform_name}"}
        try:
            message_chain = await build_message_chain_from_payload(message_payload, None, strict=True)
            await platform_inst.send_by_session(session, message_chain)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

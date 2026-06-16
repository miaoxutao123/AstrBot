"""Unified dispatcher — routes envelopes to all enabled channels."""

import asyncio
from astrbot.core import logger
from .envelope import MessageEnvelope
from .webhook import WebhookPusher
from .longpoll import LongPollQueue
from .websocket import GatewayWebSocketHandler


class GatewayDispatcher:
    """Routes messages to Webhook, LongPoll and WebSocket channels."""

    def __init__(self, config: dict):
        self.cfg = config
        self.webhook = WebhookPusher(config.get("webhook", {}))
        self.longpoll = LongPollQueue(config.get("longpoll", {}))
        self.ws_handler = GatewayWebSocketHandler(config.get("websocket", {}))
        self._enabled = config.get("enabled", True)

    async def initialize(self):
        await self.webhook.initialize()
        await self.ws_handler.initialize()

    async def dispatch(self, envelope: MessageEnvelope) -> str | None:
        """Dispatch to all channels. Returns webhook response text if any."""
        if not self._enabled:
            return None
        result = None
        if self.webhook.enabled:
            result = await self.webhook.push(envelope)
        # Fire-and-forget for longpoll and websocket
        if self.longpoll.enabled:
            asyncio.create_task(self.longpoll.enqueue(envelope))
        if self.ws_handler.enabled:
            asyncio.create_task(self.ws_handler.broadcast(envelope))
        return result

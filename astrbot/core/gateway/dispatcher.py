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

    async def dispatch(self, envelope: MessageEnvelope):
        if not self._enabled:
            return
        tasks = []
        if self.webhook.enabled:
            tasks.append(self.webhook.push(envelope))
        if self.longpoll.enabled:
            tasks.append(self.longpoll.enqueue(envelope))
        if self.ws_handler.enabled:
            tasks.append(self.ws_handler.broadcast(envelope))
        if tasks:
            asyncio.create_task(self._fire_and_forget(tasks))

    async def _fire_and_forget(self, tasks):
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.debug(f"Gateway dispatch error: {e}")

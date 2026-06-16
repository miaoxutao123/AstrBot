"""Webhook pusher — HTTP POST to external Agent endpoints."""

import asyncio
import aiohttp
from astrbot.core import logger
from .envelope import MessageEnvelope


class WebhookEndpoint:
    def __init__(self, name: str, url: str, secret: str, timeout: int, filter_cfg: dict):
        self.name = name
        self.url = url
        self.secret = secret
        self.timeout = timeout
        self.filter_platforms = set(filter_cfg.get("platforms", []))

    def accepts(self, platform_name: str) -> bool:
        return not self.filter_platforms or platform_name in self.filter_platforms


class WebhookPusher:
    def __init__(self, config: dict):
        self.enabled = config.get("enabled", False)
        self.endpoints: list[WebhookEndpoint] = []
        for ep in config.get("endpoints", []):
            self.endpoints.append(
                WebhookEndpoint(
                    name=ep.get("name", "unnamed"),
                    url=ep["url"],
                    secret=ep.get("secret", ""),
                    timeout=ep.get("timeout", 30),
                    filter_cfg=ep.get("filter", {}),
                )
            )
        self._session: aiohttp.ClientSession | None = None

    async def initialize(self):
        if self.enabled:
            self._session = aiohttp.ClientSession()

    async def push(self, envelope: MessageEnvelope) -> str | None:
        if not self._session:
            return None
        payload = envelope.to_dict()
        platform_name = envelope.platform.name
        for ep in self.endpoints:
            if not ep.accepts(platform_name):
                continue
            return await self._post(ep, payload)
        return None

    async def _post(self, ep: WebhookEndpoint, payload: dict) -> str | None:
        try:
            async with self._session.post(
                ep.url,
                json=payload,
                headers={"Authorization": f"Bearer {ep.secret}"},
                timeout=aiohttp.ClientTimeout(total=ep.timeout),
            ) as resp:
                if resp.status >= 400:
                    logger.warning(f"Webhook {ep.name} returned {resp.status}")
                    return None
                return await resp.text()
        except Exception as e:
            logger.warning(f"Webhook {ep.name} push failed: {e}")
            return None

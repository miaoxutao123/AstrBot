"""WS-to-invocation Bridge runtime, deliberately independent of Gateway Core."""

import asyncio
import logging
from collections import defaultdict

from astrbot_gateway_sdk import AsyncGatewayClient

from .config import BridgeConfig
from .invokers import CommandInvoker, HttpInvoker
from .protocol import invoke_for, parse_result
from .sessions import SessionStore


class AgentBridge:
    def __init__(self, config: BridgeConfig, api_key: str) -> None:
        self.config, self.client, self.sessions = config, AsyncGatewayClient(config.gateway_url, api_key=api_key), SessionStore(config.session_path)
        self._semaphore = asyncio.Semaphore(config.max_concurrency)
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tasks: set[asyncio.Task[None]] = set()
        self.invoker = CommandInvoker(config.command, config.invoke_timeout, config.max_stdout_bytes, config.env_allowlist) if config.mode == "command" else HttpInvoker(str(config.agent_url), config.invoke_timeout)

    @staticmethod
    def session_key(event: object) -> str:
        message = event.message
        if message is None: raise ValueError("event lacks IM message")
        conversation = message.raw.get("conversation", {})
        return "/".join((event.source.family, event.source.adapter_type, event.source.adapter_id, str(conversation.get("type", "unknown")), str(conversation.get("id", event.source.endpoint_id))))

    async def handle(self, event: object) -> None:
        key = self.session_key(event)
        async with self._semaphore, self._locks[key]:
            result = await self.invoker.invoke(invoke_for(event, key, self.sessions.get(key), self.config.gateway_url))
            reply, external = parse_result(result)
            if external: self.sessions.put(key, external)
            await self.client.reply(event, reply or "")

    async def run(self) -> None:
        try:
            async for event in self.client.events(family=self.config.family, event_type=self.config.event_type):
                task = asyncio.create_task(self.handle(event))
                self._tasks.add(task)
                task.add_done_callback(self._complete_task)
        finally:
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _complete_task(self, task: asyncio.Task[None]) -> None:
        """Retrieve task failures so individual harness errors never detach."""
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logging.getLogger("astrbot_gateway_agent").error("agent invocation failed", exc_info=error)

    async def aclose(self) -> None:
        self.sessions.close(); await self.client.aclose()

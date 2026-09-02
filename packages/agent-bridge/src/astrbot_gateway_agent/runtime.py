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
        self.config, self.client, self.sessions = (
            config,
            AsyncGatewayClient(config.gateway_url, api_key=api_key),
            SessionStore(config.session_path),
        )
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._queue: asyncio.Queue[object] = asyncio.Queue(config.max_pending)
        self.invoker = (
            CommandInvoker(
                config.command,
                config.invoke_timeout,
                config.max_stdout_bytes,
                config.env_allowlist,
            )
            if config.mode == "command"
            else HttpInvoker(str(config.agent_url), config.invoke_timeout)
        )

    @staticmethod
    def session_key(event: object) -> str:
        message = event.message
        if message is None:
            raise ValueError("event lacks IM message")
        conversation = message.raw.get("conversation", {})
        return "/".join(
            (
                event.source.family,
                event.source.adapter_type,
                event.source.adapter_id,
                str(conversation.get("type", "unknown")),
                str(conversation.get("id", event.source.endpoint_id)),
            )
        )

    async def handle(self, event: object) -> None:
        key = self.session_key(event)
        async with self._locks[key]:
            result = await self.invoker.invoke(
                invoke_for(event, key, self.sessions.get(key), self.config.gateway_url)
            )
            reply, external = parse_result(result)
            if external:
                self.sessions.put(key, external)
            await self.client.respond(event, reply or "")

    async def _worker(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self.handle(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger("astrbot_gateway_agent").exception(
                    "agent invocation failed"
                )
            finally:
                self._queue.task_done()

    async def run(self) -> None:
        workers = [
            asyncio.create_task(self._worker())
            for _ in range(self.config.max_concurrency)
        ]
        try:
            async for event in self.client.events(
                family=self.config.family, event_type=self.config.event_type
            ):
                await self._queue.put(event)
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def aclose(self) -> None:
        self.sessions.close()
        await self.client.aclose()

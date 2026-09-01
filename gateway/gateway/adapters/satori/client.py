"""Optional-dependency Satori WebSocket and HTTP client."""

import asyncio
import json
import mimetypes
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, cast
from urllib.parse import urlparse

from gateway.core import AdapterState

from .config import SatoriConfig
from .errors import SatoriAuthenticationError, SatoriNetworkError, SatoriRequestError
from .protocol import IDENTIFY, PING, SatoriLogin

EnvelopeHandler = Callable[[Mapping[str, Any]], Awaitable[None]]
StateHandler = Callable[[AdapterState, str | None], None]


class SatoriClient(Protocol):
    async def start(
        self, handler: EnvelopeHandler, report_state: StateHandler
    ) -> None: ...
    async def stop(self) -> None: ...
    async def call(
        self, method: str, path: str, data: Mapping[str, Any], login: SatoriLogin
    ) -> Mapping[str, Any]: ...
    async def download(
        self, url: str, max_size: int
    ) -> tuple[bytes, str | None, str | None]: ...


class AiohttpSatoriClient:
    """Run Satori signaling in a background task and expose HTTP operations."""

    def __init__(
        self, config: SatoriConfig, token: str | None, sequence: int = 0
    ) -> None:
        self.config = config
        self.token = token
        self.sequence = sequence
        self._session: Any = None
        self._socket: Any = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self, handler: EnvelopeHandler, report_state: StateHandler) -> None:
        try:
            import aiohttp
        except ImportError as exc:
            raise SatoriNetworkError("aiohttp is unavailable") from exc
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.request_timeout)
        )
        self._stopping = False
        report_state(AdapterState.DEGRADED, "connecting to Satori")
        self._task = asyncio.create_task(
            self._run(handler, report_state), name="satori-websocket"
        )

    async def _run(self, handler: EnvelopeHandler, report_state: StateHandler) -> None:
        delay = 1.0
        while not self._stopping:
            try:
                from websockets.asyncio.client import connect

                async with connect(
                    self.config.endpoint, max_size=10 * 1024 * 1024
                ) as socket:
                    self._socket = socket
                    body: dict[str, Any] = {"token": self.token or ""}
                    if self.sequence > 0:
                        body["sn"] = self.sequence
                    await socket.send(json.dumps({"op": IDENTIFY, "body": body}))
                    report_state(AdapterState.RUNNING, None)
                    heartbeat = asyncio.create_task(self._heartbeat(socket))
                    try:
                        async for raw in socket:
                            value = json.loads(raw)
                            if isinstance(value, Mapping):
                                body_value = value.get("body")
                                if isinstance(body_value, Mapping) and isinstance(
                                    body_value.get("sn"), int
                                ):
                                    self.sequence = body_value["sn"]
                                await handler(cast(Mapping[str, Any], value))
                    finally:
                        heartbeat.cancel()
                        await asyncio.gather(heartbeat, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stopping:
                    return
                report_state(AdapterState.DEGRADED, "Satori disconnected; reconnecting")
                try:
                    await asyncio.wait_for(asyncio.sleep(delay), timeout=delay + 0.1)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, self.config.reconnect_max_delay)
                if isinstance(exc, SatoriAuthenticationError):
                    report_state(AdapterState.FAILED, str(exc))
                    return
            else:
                delay = 1.0

    async def _heartbeat(self, socket: Any) -> None:
        while not self._stopping:
            await asyncio.sleep(self.config.heartbeat_interval)
            await socket.send(json.dumps({"op": PING, "body": {}}))

    async def stop(self) -> None:
        self._stopping = True
        if self._socket is not None:
            await self._socket.close()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self._session is not None:
            await self._session.close()
        self._task = None
        self._socket = None
        self._session = None

    async def call(
        self, method: str, path: str, data: Mapping[str, Any], login: SatoriLogin
    ) -> Mapping[str, Any]:
        if self._session is None:
            raise SatoriNetworkError("Satori client is not started")
        headers = {"satori-platform": login.platform, "satori-user-id": login.self_id}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            async with self._session.request(
                method,
                f"{self.config.api_base_url}/{path.lstrip('/')}",
                json=dict(data),
                headers=headers,
            ) as response:
                if response.status in {401, 403}:
                    raise SatoriAuthenticationError(
                        "Satori authentication was rejected"
                    )
                if response.status >= 400:
                    raise SatoriRequestError(
                        f"Satori operation failed with HTTP {response.status}"
                    )
                value = await response.json(content_type=None)
        except (SatoriAuthenticationError, SatoriRequestError):
            raise
        except Exception as exc:
            raise SatoriNetworkError("Satori operation failed") from exc
        if isinstance(value, list):
            value = value[0] if value else {}
        if not isinstance(value, Mapping):
            raise SatoriRequestError("Satori response is not an object")
        return cast(Mapping[str, Any], value)

    async def download(
        self, url: str, max_size: int
    ) -> tuple[bytes, str | None, str | None]:
        if self._session is None:
            raise SatoriNetworkError("Satori client is not started")
        try:
            async with self._session.get(url) as response:
                if response.status >= 400:
                    raise SatoriRequestError(
                        f"Satori media failed with HTTP {response.status}"
                    )
                data = await response.read()
                mime_type = (
                    response.headers.get("Content-Type", "").split(";", 1)[0] or None
                )
        except SatoriRequestError:
            raise
        except Exception as exc:
            raise SatoriNetworkError("Satori media download failed") from exc
        if len(data) > max_size:
            raise SatoriRequestError("Satori media exceeds Gateway limit")
        filename = urlparse(url).path.rsplit("/", 1)[-1] or None
        return data, mime_type or (mimetypes.guess_type(filename or "")[0]), filename


def create_client(
    config: SatoriConfig, token: str | None, sequence: int = 0
) -> SatoriClient:
    return AiohttpSatoriClient(config, token, sequence)

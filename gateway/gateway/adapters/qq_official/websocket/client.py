"""Tencent QQ Official Gateway WebSocket and REST client."""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, cast
from urllib.parse import urlparse

from gateway.core import AdapterState

from ..common.errors import (
    QQOfficialAuthenticationError,
    QQOfficialDeliveryError,
    QQOfficialNetworkError,
    QQOfficialRateLimitError,
    QQOfficialRequestError,
    QQOfficialTimeoutError,
)
from .config import QQOfficialWebSocketConfig

DispatchHandler = Callable[[str, Mapping[str, Any]], Awaitable[None]]
StateHandler = Callable[[AdapterState, str | None], None]
CredentialHandler = Callable[[str | None, float], Awaitable[None]]
SessionHandler = Callable[[str | None, int | None, str | None], Awaitable[None]]


class QQOfficialWebSocketClient(Protocol):
    async def start(
        self,
        dispatch: DispatchHandler,
        report_state: StateHandler,
        credential: CredentialHandler,
        session: SessionHandler,
    ) -> None: ...
    async def stop(self) -> None: ...
    async def request(
        self, method: str, path: str, data: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]: ...
    async def download(
        self, url: str, max_size: int
    ) -> tuple[bytes, str | None, str | None]: ...


class TencentGatewayClient:
    def __init__(
        self,
        config: QQOfficialWebSocketConfig,
        app_id: str,
        secret: str,
        access_token: str | None = None,
        expires_at: float = 0,
        session_id: str | None = None,
        sequence: int | None = None,
        resume_url: str | None = None,
    ) -> None:
        self.config = config
        self.app_id = app_id
        self.secret = secret
        self.access_token = access_token
        self.expires_at = expires_at
        self.session_id = session_id
        self.sequence = sequence
        self.resume_url = resume_url
        self._session: Any = None
        self._socket: Any = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._credential: CredentialHandler | None = None
        self._session_handler: SessionHandler | None = None

    async def start(
        self,
        dispatch: DispatchHandler,
        report_state: StateHandler,
        credential: CredentialHandler,
        session: SessionHandler,
    ) -> None:
        try:
            import aiohttp
        except ImportError as exc:
            raise QQOfficialNetworkError("aiohttp is unavailable") from exc
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.common.request_timeout)
        )
        self._credential = credential
        self._session_handler = session
        self._stopping = False
        await self._ensure_token()
        report_state(AdapterState.DEGRADED, "connecting to QQ Official Gateway")
        self._task = asyncio.create_task(
            self._run(dispatch, report_state), name="qq-official-gateway"
        )

    async def _ensure_token(self) -> None:
        if self.access_token and self.expires_at > time.time() + 60:
            return
        if self._session is None:
            raise QQOfficialNetworkError("QQ Official client is not started")
        try:
            async with self._session.post(
                self.config.common.auth_url,
                json={"appId": self.app_id, "clientSecret": self.secret},
            ) as response:
                value = await response.json(content_type=None)
                if response.status in {401, 403}:
                    raise QQOfficialAuthenticationError(
                        "QQ Official credentials were rejected"
                    )
                if response.status >= 400 or not isinstance(value, Mapping):
                    raise QQOfficialAuthenticationError(
                        "QQ Official access token request failed"
                    )
        except QQOfficialAuthenticationError:
            raise
        except Exception as exc:
            raise QQOfficialNetworkError(
                "QQ Official access token request failed"
            ) from exc
        token = value.get("access_token")
        expires_in = value.get("expires_in", 0)
        if not isinstance(token, str) or not token:
            raise QQOfficialAuthenticationError(
                "QQ Official access token response is invalid"
            )
        try:
            lifetime = float(expires_in)
        except (TypeError, ValueError):
            lifetime = 0
        self.access_token = token
        self.expires_at = time.time() + max(lifetime, 60)
        if self._credential is not None:
            await self._credential(token, self.expires_at)

    async def _invalidate_token(self) -> None:
        self.access_token = None
        self.expires_at = 0
        if self._credential is not None:
            await self._credential(None, 0)

    async def _gateway_url(self) -> str:
        value = await self.request("GET", "/gateway/bot")
        url = value.get("url")
        if not isinstance(url, str) or not url.startswith(("ws://", "wss://")):
            raise QQOfficialRequestError("QQ Official gateway discovery is invalid")
        return url

    async def _run(self, dispatch: DispatchHandler, report_state: StateHandler) -> None:
        delay = 1.0
        while not self._stopping:
            try:
                from websockets.asyncio.client import connect

                await self._ensure_token()
                gateway_url = self.resume_url or await self._gateway_url()
                async with connect(gateway_url, max_size=10 * 1024 * 1024) as socket:
                    self._socket = socket
                    should_reconnect = await self._connection(
                        socket, dispatch, report_state
                    )
                    if not should_reconnect:
                        return
            except asyncio.CancelledError:
                raise
            except QQOfficialAuthenticationError as exc:
                report_state(AdapterState.FAILED, str(exc))
                return
            except QQOfficialTimeoutError as exc:
                if self._stopping:
                    return
                report_state(AdapterState.DEGRADED, str(exc))
            except Exception:
                if self._stopping:
                    return
                report_state(
                    AdapterState.DEGRADED, "QQ Official disconnected; reconnecting"
                )
            try:
                await asyncio.wait_for(asyncio.sleep(delay), delay + 0.1)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, self.config.reconnect_max_delay)

    async def _connection(
        self, socket: Any, dispatch: DispatchHandler, report_state: StateHandler
    ) -> bool:
        acknowledged = [True]
        heartbeat: asyncio.Task[None] | None = None
        heartbeat_errors: list[Exception] = []
        try:
            async for raw in socket:
                envelope = json.loads(raw)
                if not isinstance(envelope, Mapping):
                    continue
                op = envelope.get("op")
                if isinstance(envelope.get("s"), int):
                    self.sequence = envelope["s"]
                if op == 10:
                    data = envelope.get("d")
                    interval_ms = (
                        data.get("heartbeat_interval")
                        if isinstance(data, Mapping)
                        else None
                    )
                    if not isinstance(interval_ms, int | float) or interval_ms <= 0:
                        raise QQOfficialRequestError("QQ Official HELLO is invalid")
                    if self.session_id and self.sequence is not None:
                        payload = {
                            "op": 6,
                            "d": {
                                "token": f"QQBot {self.access_token}",
                                "session_id": self.session_id,
                                "seq": self.sequence,
                            },
                        }
                    else:
                        payload = {
                            "op": 2,
                            "d": {
                                "token": f"QQBot {self.access_token}",
                                "intents": self.config.intents,
                                "shard": [0, 1],
                                "properties": {
                                    "$os": "gateway",
                                    "$browser": "astrbot-gateway",
                                    "$device": "astrbot-gateway",
                                },
                            },
                        }
                    await socket.send(json.dumps(payload))
                    heartbeat = asyncio.create_task(
                        self._supervise_heartbeat(
                            socket,
                            float(interval_ms) / 1000,
                            acknowledged,
                            heartbeat_errors,
                        )
                    )
                elif op == 11:
                    acknowledged[0] = True
                elif op == 7:
                    return True
                elif op == 9:
                    self.session_id = None
                    self.sequence = None
                    self.resume_url = None
                    if self._session_handler:
                        await self._session_handler(None, None, None)
                    return True
                elif op == 0:
                    event_type = envelope.get("t")
                    data = envelope.get("d")
                    if event_type == "READY" and isinstance(data, Mapping):
                        self.session_id = str(data.get("session_id") or "") or None
                        self.resume_url = (
                            str(data.get("resume_gateway_url") or "") or None
                        )
                        if self._session_handler:
                            await self._session_handler(
                                self.session_id, self.sequence, self.resume_url
                            )
                        report_state(AdapterState.RUNNING, None)
                    elif event_type == "RESUMED":
                        report_state(AdapterState.RUNNING, None)
                    elif isinstance(event_type, str) and isinstance(data, Mapping):
                        if self._session_handler:
                            await self._session_handler(
                                self.session_id, self.sequence, self.resume_url
                            )
                        await dispatch(event_type, cast(Mapping[str, Any], data))
        finally:
            if heartbeat is not None:
                if not heartbeat.done():
                    heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
        if heartbeat_errors:
            raise heartbeat_errors[0]
        return True

    async def _supervise_heartbeat(
        self,
        socket: Any,
        interval: float,
        acknowledged: list[bool],
        errors: list[Exception],
    ) -> None:
        try:
            await self._heartbeat(socket, interval, acknowledged)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            errors.append(exc)
            await socket.close()

    async def _heartbeat(
        self, socket: Any, interval: float, acknowledged: list[bool]
    ) -> None:
        while not self._stopping:
            await asyncio.sleep(interval)
            if not acknowledged[0]:
                await socket.close()
                raise QQOfficialTimeoutError("QQ Official heartbeat ACK timed out")
            await socket.send(json.dumps({"op": 1, "d": self.sequence}))
            acknowledged[0] = False

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

    async def request(
        self, method: str, path: str, data: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        return await self._request(method, path, data, allow_token_refresh=True)

    async def _request(
        self,
        method: str,
        path: str,
        data: Mapping[str, Any] | None,
        *,
        allow_token_refresh: bool,
    ) -> Mapping[str, Any]:
        await self._ensure_token()
        if self._session is None:
            raise QQOfficialNetworkError("QQ Official client is not started")
        headers = {
            "Authorization": f"QQBot {self.access_token}",
            "X-Union-Appid": self.app_id,
        }
        try:
            async with self._session.request(
                method,
                f"{self.config.common.api_base_url}/{path.lstrip('/')}",
                json=dict(data) if data is not None else None,
                headers=headers,
            ) as response:
                retry_header = response.headers.get("Retry-After")
                if response.status == 429:
                    raise QQOfficialRateLimitError(
                        "QQ Official rate limit exceeded",
                        float(retry_header) if retry_header else None,
                    )
                if response.status in {401, 403}:
                    await self._invalidate_token()
                    if allow_token_refresh:
                        await self._ensure_token()
                        return await self._request(
                            method, path, data, allow_token_refresh=False
                        )
                    raise QQOfficialAuthenticationError(
                        "QQ Official access token was rejected after refresh"
                    )
                value = await response.json(content_type=None)
                if response.status >= 500:
                    raise QQOfficialDeliveryError(
                        f"QQ Official delivery failed with HTTP {response.status}"
                    )
                if response.status >= 400:
                    raise QQOfficialRequestError(
                        f"QQ Official request failed with HTTP {response.status}"
                    )
        except (
            QQOfficialAuthenticationError,
            QQOfficialRateLimitError,
            QQOfficialRequestError,
            QQOfficialDeliveryError,
        ):
            raise
        except asyncio.TimeoutError as exc:
            raise QQOfficialTimeoutError("QQ Official request timed out") from exc
        except Exception as exc:
            raise QQOfficialNetworkError("QQ Official request failed") from exc
        if not isinstance(value, Mapping):
            raise QQOfficialRequestError("QQ Official response is not an object")
        return cast(Mapping[str, Any], value)

    async def download(
        self, url: str, max_size: int
    ) -> tuple[bytes, str | None, str | None]:
        if self._session is None:
            raise QQOfficialNetworkError("QQ Official client is not started")
        async with self._session.get(url) as response:
            if response.status >= 400:
                raise QQOfficialRequestError(
                    f"QQ Official media failed with HTTP {response.status}"
                )
            data = await response.read()
            mime = response.headers.get("Content-Type", "").split(";", 1)[0] or None
        if len(data) > max_size:
            raise QQOfficialRequestError("QQ Official media exceeds Gateway limit")
        return data, mime, urlparse(url).path.rsplit("/", 1)[-1] or None

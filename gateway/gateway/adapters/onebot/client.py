"""OneBot v11 forward and aiocqhttp-compatible reverse WebSocket clients.

This module is a transport-focused rewrite informed by AstrBot's
`astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py` at
upstream commit 0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d. It contains no AstrBot runtime,
message, plugin, pipeline, provider, or agent dependency.
"""

import asyncio
import inspect
import json
import mimetypes
import uuid
from collections.abc import Awaitable, Callable, Mapping
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from gateway.core import AdapterState

from .config import OneBotConfig
from .errors import (
    OneBotActionError,
    OneBotDisconnectedError,
)

EventHandler = Callable[[Mapping[str, Any]], Awaitable[None]]
StateHandler = Callable[[AdapterState, str | None], None]


class OneBotClient(Protocol):
    """Narrow client surface consumed by OneBotAdapter."""

    async def start(
        self,
        on_event: EventHandler,
        report_state: StateHandler,
    ) -> None:
        """Create receive resources and return immediately."""
        ...

    async def stop(self) -> None:
        """Stop receive resources and close connections."""
        ...

    async def call_action(self, action: str, **params: Any) -> Mapping[str, Any]:
        """Call one OneBot action and return its data."""
        ...

    async def download(
        self,
        url: str,
        max_size: int,
    ) -> tuple[bytes, str, str]:
        """Download bounded platform media."""
        ...


async def download_media(url: str, max_size: int) -> tuple[bytes, str, str]:
    """Download bounded HTTP media for the generic Gateway media store.

    Args:
        url: Platform-provided HTTP or HTTPS URL.
        max_size: Maximum response bytes.

    Returns:
        Bytes, MIME type, and display filename.

    Raises:
        ValueError: If URL, response, or size is invalid.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("OneBot media URL is invalid")
    try:
        import aiohttp
    except ImportError as exc:
        raise RuntimeError(
            "OneBot media download requires the onebot optional dependency"
        ) from exc
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, allow_redirects=True) as response:
            if response.status < 200 or response.status >= 300:
                raise ValueError("OneBot media download failed")
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > max_size:
                raise ValueError("OneBot media exceeds the configured size limit")
            data = await response.content.read(max_size + 1)
            if len(data) > max_size:
                raise ValueError("OneBot media exceeds the configured size limit")
            mime_type = response.headers.get("Content-Type", "").split(";", 1)[0]
    filename = unquote(PurePosixPath(parsed.path).name) or "onebot-media.bin"
    if not mime_type:
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return data, mime_type, filename


class ForwardWebSocketClient:
    """OneBot v11 forward WebSocket client with bounded reconnect backoff.

    Args:
        config: Validated OneBot adapter configuration.
        token: Resolved optional access token.
    """

    def __init__(self, config: OneBotConfig, token: str | None) -> None:
        self._config = config
        self._token = token
        self._on_event: EventHandler | None = None
        self._report_state: StateHandler | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._websocket: Any = None
        self._pending: dict[str, asyncio.Future[Mapping[str, Any]]] = {}

    async def start(
        self,
        on_event: EventHandler,
        report_state: StateHandler,
    ) -> None:
        """Start the reconnect loop.

        Args:
            on_event: Async event callback.
            report_state: Adapter health callback.

        Raises:
            RuntimeError: If already started.
        """
        if self._task is not None:
            raise RuntimeError("OneBot client is already started")
        self._on_event = on_event
        self._report_state = report_state
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="onebot-forward-websocket",
        )

    async def _run(self) -> None:
        try:
            import aiohttp
        except ImportError:
            assert self._report_state is not None
            self._report_state(
                AdapterState.FAILED,
                "OneBot websocket mode requires the onebot optional dependency",
            )
            return
        assert self._config.endpoint is not None
        assert self._report_state is not None
        delay = 1.0
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        timeout = aiohttp.ClientTimeout(total=None, connect=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while not self._stop.is_set():
                terminal_failure = False
                try:
                    async with session.ws_connect(
                        self._config.endpoint,
                        headers=headers,
                        heartbeat=20,
                    ) as websocket:
                        self._websocket = websocket
                        delay = 1.0
                        self._report_state(AdapterState.RUNNING, None)
                        async for message in websocket:
                            if message.type == aiohttp.WSMsgType.TEXT:
                                payload = json.loads(message.data)
                                if isinstance(payload, Mapping):
                                    await self._dispatch(payload)
                            elif message.type in {
                                aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            }:
                                break
                except asyncio.CancelledError:
                    raise
                except aiohttp.WSServerHandshakeError as exc:
                    if exc.status in {401, 403}:
                        terminal_failure = True
                        self._report_state(
                            AdapterState.FAILED,
                            "OneBot access token was rejected",
                        )
                        return
                    self._report_state(
                        AdapterState.DEGRADED,
                        f"OneBot connection failed with HTTP {exc.status}",
                    )
                except Exception:
                    self._report_state(
                        AdapterState.DEGRADED,
                        "OneBot connection was lost; reconnecting",
                    )
                finally:
                    self._websocket = None
                    for future in self._pending.values():
                        if not future.done():
                            future.set_exception(
                                OneBotDisconnectedError("OneBot connection was lost")
                            )
                    self._pending.clear()
                    if not self._stop.is_set() and not terminal_failure:
                        self._report_state(
                            AdapterState.DEGRADED,
                            "OneBot connection was lost; reconnecting",
                        )
                if self._stop.is_set():
                    return
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, self._config.reconnect_max_delay)

    async def _dispatch(self, payload: Mapping[str, Any]) -> None:
        echo = payload.get("echo")
        if isinstance(echo, str) and echo in self._pending:
            future = self._pending.pop(echo)
            if payload.get("status") == "ok" or payload.get("retcode") == 0:
                data = payload.get("data")
                future.set_result(data if isinstance(data, Mapping) else {})
            else:
                future.set_exception(OneBotActionError("OneBot action failed"))
            return
        if self._on_event is not None:
            await self._on_event(payload)

    async def stop(self) -> None:
        """Stop reconnecting and close the active WebSocket."""
        self._stop.set()
        if self._websocket is not None and not self._websocket.closed:
            await self._websocket.close(code=1000, message=b"Gateway shutdown")
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def call_action(self, action: str, **params: Any) -> Mapping[str, Any]:
        """Send an action over the active WebSocket.

        Args:
            action: OneBot action name.
            **params: OneBot action parameters.

        Returns:
            Successful response data.

        Raises:
            OneBotDisconnectedError: If no action channel is connected.
            OneBotActionError: If the action times out or fails.
        """
        websocket = self._websocket
        if websocket is None or websocket.closed:
            raise OneBotDisconnectedError("OneBot is not connected")
        echo = uuid.uuid4().hex
        future: asyncio.Future[Mapping[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[echo] = future
        try:
            await websocket.send_json(
                {"action": action, "params": params, "echo": echo}
            )
            return await asyncio.wait_for(
                future,
                timeout=self._config.action_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise OneBotActionError("OneBot action timed out") from exc
        finally:
            self._pending.pop(echo, None)

    async def download(
        self,
        url: str,
        max_size: int,
    ) -> tuple[bytes, str, str]:
        """Download bounded platform media.

        Args:
            url: Platform-provided media URL.
            max_size: Maximum response bytes.

        Returns:
            Bytes, MIME type, and filename.
        """
        return await download_media(url, max_size)


class ReverseWebSocketClient:
    """aiocqhttp reverse WebSocket server compatibility client.

    Args:
        config: Validated OneBot adapter configuration.
        token: Resolved optional access token.
    """

    def __init__(self, config: OneBotConfig, token: str | None) -> None:
        self._config = config
        self._token = token
        self._bot: Any = None
        self._task: asyncio.Task[None] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._shutdown = asyncio.Event()
        self._report_state: StateHandler | None = None

    async def start(
        self,
        on_event: EventHandler,
        report_state: StateHandler,
    ) -> None:
        """Start the reverse WebSocket server tasks.

        Args:
            on_event: Async event callback.
            report_state: Adapter health callback.

        Raises:
            RuntimeError: If aiocqhttp is unavailable or already started.
        """
        if self._task is not None:
            raise RuntimeError("OneBot client is already started")
        try:
            from aiocqhttp import CQHttp  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "OneBot reverse mode requires the onebot optional dependency"
            ) from exc
        self._report_state = report_state
        self._bot = CQHttp(
            use_ws_reverse=True,
            import_name="astrbot_gateway_onebot",
            api_timeout_sec=self._config.action_timeout,
            access_token=self._token,
        )

        async def handle(event: Mapping[str, Any]) -> None:
            await on_event(dict(event))

        self._bot.on_message()(handle)
        self._bot.on_notice()(handle)
        self._bot.on_request()(handle)

        @self._bot.on_websocket_connection  # type: ignore[untyped-decorator]
        def connected(_event: Any) -> None:
            report_state(AdapterState.RUNNING, None)

        self._shutdown.clear()
        self._task = asyncio.create_task(
            self._run_server(),
            name="onebot-reverse-websocket",
        )
        self._monitor_task = asyncio.create_task(
            self._monitor_connections(),
            name="onebot-reverse-monitor",
        )

    async def _run_server(self) -> None:
        assert self._bot is not None
        assert self._report_state is not None
        try:
            await self._bot.run_task(
                host=self._config.host,
                port=self._config.port,
                shutdown_trigger=self._shutdown.wait,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            self._report_state(
                AdapterState.FAILED,
                "OneBot reverse WebSocket server failed",
            )

    async def _monitor_connections(self) -> None:
        assert self._report_state is not None
        was_connected = False
        while not self._shutdown.is_set():
            api_clients = getattr(self._bot, "_wsr_api_clients", None)
            event_clients = getattr(self._bot, "_wsr_event_clients", None)
            connected = bool(api_clients) or bool(event_clients)
            if was_connected and not connected:
                self._report_state(
                    AdapterState.DEGRADED,
                    "OneBot reverse WebSocket client disconnected",
                )
            was_connected = connected
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        """Stop the reverse server and close private SDK WebSocket collections."""
        self._shutdown.set()
        api_clients = getattr(self._bot, "_wsr_api_clients", None)
        event_clients = getattr(self._bot, "_wsr_event_clients", None)
        clients: set[Any] = set()
        if isinstance(api_clients, dict):
            clients.update(api_clients.values())
        if isinstance(event_clients, set):
            clients.update(event_clients)
        close_tasks: list[Awaitable[Any]] = []
        for websocket in clients:
            close = getattr(websocket, "close", None)
            if not callable(close):
                continue
            try:
                result = close(code=1000, reason="Gateway shutdown")
            except TypeError:
                result = close()
            if inspect.isawaitable(result):
                close_tasks.append(result)
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        tasks = [task for task in (self._monitor_task, self._task) if task is not None]
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=5)
            for task in pending:
                task.cancel()
            await asyncio.gather(*done, *pending, return_exceptions=True)
        self._monitor_task = None
        self._task = None
        self._bot = None

    async def call_action(self, action: str, **params: Any) -> Mapping[str, Any]:
        """Call an action through aiocqhttp.

        Args:
            action: OneBot action name.
            **params: OneBot action parameters.

        Returns:
            Successful response data.

        Raises:
            OneBotDisconnectedError: If the reverse server is not started.
            OneBotActionError: If the SDK reports an action failure.
        """
        if self._bot is None:
            raise OneBotDisconnectedError("OneBot reverse server is not started")
        try:
            result = await self._bot.call_action(action=action, **params)
        except Exception as exc:
            raise OneBotActionError("OneBot action failed") from exc
        return result if isinstance(result, Mapping) else {}

    async def download(
        self,
        url: str,
        max_size: int,
    ) -> tuple[bytes, str, str]:
        """Download bounded platform media.

        Args:
            url: Platform-provided media URL.
            max_size: Maximum response bytes.

        Returns:
            Bytes, MIME type, and filename.
        """
        return await download_media(url, max_size)


def create_client(config: OneBotConfig, token: str | None) -> OneBotClient:
    """Create the configured OneBot transport client.

    Args:
        config: Validated OneBot configuration.
        token: Resolved optional access token.

    Returns:
        Forward or reverse WebSocket client.
    """
    if config.mode == "reverse_websocket":
        return ReverseWebSocketClient(config, token)
    return ForwardWebSocketClient(config, token)

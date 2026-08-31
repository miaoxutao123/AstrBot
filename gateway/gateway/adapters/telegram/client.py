"""Telegram Bot API polling client isolated from Gateway Core.

This module selectively rewrites transport lifecycle behavior audited from
`astrbot/core/platform/sources/telegram/tg_adapter.py` at upstream commit
0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d. It intentionally excludes AstrBot
commands, plugins, MessageChain, streaming generators, and Agent behavior.
"""

import asyncio
import mimetypes
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import PurePosixPath
from typing import Any, Protocol, cast
from urllib.parse import urlparse

from gateway.core import AdapterState

from .config import TelegramConfig
from .errors import (
    TelegramAuthenticationError,
    TelegramError,
    TelegramNetworkError,
    TelegramRateLimitError,
    TelegramRequestError,
)

UpdateHandler = Callable[[Mapping[str, Any]], Awaitable[None]]
StateHandler = Callable[[AdapterState, str | None], None]


@dataclass(frozen=True, slots=True)
class TelegramUpload:
    """Carry media bytes to the SDK boundary.

    Args:
        data: Media content.
        filename: Safe display filename.
    """

    data: bytes
    filename: str


class TelegramClient(Protocol):
    """Narrow client surface consumed by TelegramAdapter."""

    async def start(
        self,
        on_update: UpdateHandler,
        report_state: StateHandler,
    ) -> None:
        """Create polling work and return immediately."""
        ...

    async def stop(self) -> None:
        """Stop polling and release SDK resources."""
        ...

    async def call(self, method: str, **params: Any) -> Mapping[str, Any]:
        """Call a Telegram Bot method."""
        ...

    async def download(
        self,
        file_id: str,
        max_size: int,
    ) -> tuple[bytes, str, str]:
        """Download a Telegram file into the media boundary."""
        ...


def _translate_error(
    exc: Exception,
    *,
    authentication_context: bool = False,
) -> TelegramError:
    """Translate python-telegram-bot exceptions without leaking token data."""
    try:
        from telegram.error import (
            BadRequest,
            Forbidden,
            InvalidToken,
            NetworkError,
            RetryAfter,
            TimedOut,
        )
    except ImportError:
        return TelegramNetworkError("Telegram SDK is unavailable")
    if isinstance(exc, InvalidToken) or (
        authentication_context and isinstance(exc, Forbidden)
    ):
        return TelegramAuthenticationError("Telegram authentication failed")
    if isinstance(exc, RetryAfter):
        retry_after = exc.retry_after
        seconds = (
            retry_after.total_seconds()
            if isinstance(retry_after, timedelta)
            else float(retry_after)
        )
        return TelegramRateLimitError(seconds)
    if isinstance(exc, BadRequest | Forbidden):
        return TelegramRequestError("Telegram rejected the request")
    if isinstance(exc, NetworkError | TimedOut):
        return TelegramNetworkError("Telegram network request failed")
    return TelegramNetworkError("Telegram transport failed")


class TelegramPollingClient:
    """python-telegram-bot polling client with explicit health transitions.

    Args:
        config: Validated adapter configuration.
        token: Resolved bot token.
    """

    def __init__(self, config: TelegramConfig, token: str) -> None:
        self._config = config
        self._token = token
        self._application: Any = None
        self._task: asyncio.Task[None] | None = None
        self._health_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._report_state: StateHandler | None = None
        self._on_update: UpdateHandler | None = None
        self._degraded = False
        self._terminal_failure = False

    async def start(
        self,
        on_update: UpdateHandler,
        report_state: StateHandler,
    ) -> None:
        """Start the reconnecting polling loop.

        Args:
            on_update: Async normalized update callback.
            report_state: Runtime health reporter.

        Raises:
            RuntimeError: If polling is already started or the SDK is absent.
        """
        if self._task is not None:
            raise RuntimeError("Telegram client is already started")
        try:
            import telegram  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Telegram requires the telegram optional dependency"
            ) from exc
        self._on_update = on_update
        self._report_state = report_state
        self._stop.clear()
        self._terminal_failure = False
        self._task = asyncio.create_task(self._run(), name="telegram-polling")

    def _build_application(self) -> Any:
        from telegram import Update
        from telegram.ext import ApplicationBuilder, TypeHandler

        application = (
            ApplicationBuilder()
            .token(self._token)
            .base_url(self._config.base_url)
            .base_file_url(self._config.file_base_url)
            .build()
        )

        async def handle(update: Any, _context: Any) -> None:
            if self._on_update is None:
                return
            value = update.to_dict()
            if isinstance(value, Mapping):
                await self._on_update(value)

        application.add_handler(TypeHandler(Update, handle))
        return application

    async def _run(self) -> None:
        assert self._report_state is not None
        delay = 1.0
        while not self._stop.is_set():
            try:
                from telegram import Update

                self._application = self._build_application()
                await self._application.initialize()
                await self._application.start()
                updater = self._application.updater
                if updater is None:
                    raise TelegramNetworkError("Telegram polling updater is missing")
                await updater.start_polling(
                    timeout=self._config.polling_timeout,
                    error_callback=self._polling_error,
                    allowed_updates=Update.ALL_TYPES,
                )
                self._degraded = False
                delay = 1.0
                self._report_state(AdapterState.RUNNING, None)
                self._health_task = asyncio.create_task(
                    self._health_loop(),
                    name="telegram-health",
                )
                while updater.running and not self._stop.is_set():
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=0.5)
                    except asyncio.TimeoutError:
                        pass
                if not self._stop.is_set() and not self._terminal_failure:
                    raise TelegramNetworkError("Telegram polling stopped unexpectedly")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = (
                    exc
                    if isinstance(exc, TelegramError)
                    else _translate_error(exc, authentication_context=True)
                )
                if isinstance(error, TelegramAuthenticationError):
                    self._terminal_failure = True
                    self._report_state(AdapterState.FAILED, str(error))
                    return
                self._degraded = True
                self._report_state(
                    AdapterState.DEGRADED,
                    "Telegram polling failed; reconnecting",
                )
            finally:
                await self._shutdown_application()
            if self._stop.is_set() or self._terminal_failure:
                return
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, self._config.reconnect_max_delay)

    def _polling_error(self, exc: Exception) -> None:
        assert self._report_state is not None
        error = _translate_error(exc, authentication_context=True)
        if isinstance(error, TelegramAuthenticationError):
            self._terminal_failure = True
            self._report_state(AdapterState.FAILED, str(error))
            self._stop.set()
            return
        self._degraded = True
        self._report_state(AdapterState.DEGRADED, "Telegram polling network error")

    async def _health_loop(self) -> None:
        assert self._report_state is not None
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._config.health_interval,
                )
                return
            except asyncio.TimeoutError:
                pass
            try:
                await self._application.bot.get_me()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = _translate_error(exc, authentication_context=True)
                if isinstance(error, TelegramAuthenticationError):
                    self._terminal_failure = True
                    self._report_state(AdapterState.FAILED, str(error))
                    self._stop.set()
                    return
                if not self._degraded:
                    self._degraded = True
                    self._report_state(
                        AdapterState.DEGRADED,
                        "Telegram health probe failed",
                    )
            else:
                if self._degraded:
                    self._degraded = False
                    self._report_state(AdapterState.RUNNING, None)

    async def _shutdown_application(self) -> None:
        if self._health_task is not None:
            current = asyncio.current_task()
            if self._health_task is not current:
                self._health_task.cancel()
                await asyncio.gather(self._health_task, return_exceptions=True)
            self._health_task = None
        application = self._application
        if application is None:
            return
        updater = application.updater
        if updater is not None and updater.running:
            try:
                await updater.stop()
            except Exception:
                pass
        if application.running:
            try:
                await application.stop()
            except Exception:
                pass
        try:
            await application.shutdown()
        except Exception:
            pass
        self._application = None

    async def stop(self) -> None:
        """Stop polling, health probes, and SDK HTTP resources."""
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self._shutdown_application()

    async def call(self, method: str, **params: Any) -> Mapping[str, Any]:
        """Call one Bot API method through python-telegram-bot.

        Args:
            method: Bot method name.
            **params: Validated transport parameters.

        Returns:
            JSON-compatible result fields.

        Raises:
            TelegramError: If the operation fails.
        """
        if self._application is None or self._terminal_failure:
            raise TelegramNetworkError("Telegram client is not connected")
        try:
            from telegram import InputFile, ReactionTypeCustomEmoji, ReactionTypeEmoji

            upload = params.pop("_upload", None)
            if isinstance(upload, TelegramUpload):
                field = {
                    "send_photo": "photo",
                    "send_voice": "voice",
                    "send_video": "video",
                    "send_document": "document",
                }.get(method)
                if field is None:
                    raise TelegramRequestError("Telegram upload method is invalid")
                params[field] = InputFile(upload.data, filename=upload.filename)
            reaction = params.pop("_reaction", None)
            if method == "set_message_reaction":
                if reaction is None:
                    params["reaction"] = []
                elif isinstance(reaction, str) and reaction.isdigit():
                    params["reaction"] = [ReactionTypeCustomEmoji(reaction)]
                elif isinstance(reaction, str):
                    params["reaction"] = [ReactionTypeEmoji(reaction)]
                else:
                    raise TelegramRequestError("Telegram reaction is invalid")
            function = getattr(self._application.bot, method, None)
            if not callable(function):
                raise TelegramRequestError("Telegram method is unsupported")
            callable_method = cast(Callable[..., Awaitable[Any]], function)
            result = await callable_method(**params)
        except TelegramError:
            raise
        except Exception as exc:
            raise _translate_error(exc) from exc
        if isinstance(result, Mapping):
            return dict(result)
        to_dict = getattr(result, "to_dict", None)
        if callable(to_dict):
            value = to_dict()
            if isinstance(value, Mapping):
                return dict(value)
        message_id = getattr(result, "message_id", None)
        return {} if message_id is None else {"message_id": message_id}

    async def download(
        self,
        file_id: str,
        max_size: int,
    ) -> tuple[bytes, str, str]:
        """Download one bounded Telegram file.

        Args:
            file_id: Telegram file identifier.
            max_size: Maximum accepted bytes.

        Returns:
            Content, inferred MIME type, and display filename.

        Raises:
            TelegramError: If the file cannot be retrieved.
            ValueError: If it exceeds the media-store limit.
        """
        if self._application is None:
            raise TelegramNetworkError("Telegram client is not connected")
        try:
            file = await self._application.bot.get_file(file_id)
            size = getattr(file, "file_size", None)
            if isinstance(size, int) and size > max_size:
                raise ValueError("Telegram media exceeds the configured size limit")
            data = bytes(await file.download_as_bytearray())
        except ValueError:
            raise
        except Exception as exc:
            raise _translate_error(exc) from exc
        if len(data) > max_size:
            raise ValueError("Telegram media exceeds the configured size limit")
        path = str(getattr(file, "file_path", "") or "")
        parsed = urlparse(path)
        filename = PurePosixPath(parsed.path).name or f"telegram-{file_id}.bin"
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return data, mime_type, filename


def create_client(config: TelegramConfig, token: str) -> TelegramClient:
    """Create the production Telegram polling client.

    Args:
        config: Validated Telegram configuration.
        token: Resolved bot token.

    Returns:
        Polling client implementation.
    """
    return TelegramPollingClient(config, token)

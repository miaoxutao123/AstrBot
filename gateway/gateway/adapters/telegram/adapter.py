"""Agent-agnostic Telegram Bot API TransportAdapter.

Transport behavior was selectively rewritten from AstrBot's Telegram sources at
upstream commit 0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d under AGPL-3.0-or-later.
AstrBot commands, plugins, MessageChain, streaming, prompts, and Agent runtime code
are intentionally absent.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from gateway.core import (
    GATEWAY_API_VERSION,
    AdapterContext,
    AdapterDescriptor,
    AdapterState,
    Capability,
    CommandResult,
    EndpointRef,
    GatewayCommand,
    GatewayError,
    GatewayErrorCode,
    GatewayEvent,
    TransportAdapter,
)
from gateway.media import MediaStoreError
from gateway.profiles.im import (
    IM_MESSAGE_DELETE,
    IM_MESSAGE_EDIT,
    IM_MESSAGE_REPLY,
    IM_MESSAGE_SEND,
    IM_REACTION_ADD,
    IM_REACTION_REMOVE,
    IM_TYPING_SET,
    IMMessage,
    IMMessageDelete,
    IMMessageEdit,
    IMOutboundMessage,
    IMReaction,
    IMTyping,
)

from .capabilities import TELEGRAM_CAPABILITIES
from .client import TelegramClient, create_client
from .config import TelegramConfig
from .errors import (
    TelegramAuthenticationError,
    TelegramNetworkError,
    TelegramRateLimitError,
    TelegramRequestError,
)
from .inbound import convert_inbound_update
from .outbound import edit_message, parse_endpoint, send_outbound_message, send_typing
from .outbound import set_reaction as send_reaction

TelegramClientFactory = Callable[[TelegramConfig, str], TelegramClient]


@dataclass(slots=True)
class _MediaGroup:
    updates: list[Mapping[str, Any]] = field(default_factory=list)
    created_at: float = 0.0
    task: asyncio.Task[None] | None = None


class TelegramAdapter(TransportAdapter):
    """Bridge Telegram Bot API polling and Gateway IM contracts.

    Args:
        instance_id: Configured adapter instance identifier.
        config: Adapter-owned configuration.
        client_factory: Optional transport client factory for tests.
    """

    def __init__(
        self,
        instance_id: str,
        config: Mapping[str, Any] | None = None,
        client_factory: TelegramClientFactory = create_client,
    ) -> None:
        if not instance_id or not instance_id.strip():
            raise ValueError("Telegram adapter instance ID must not be empty")
        self.instance_id = instance_id
        self.config = TelegramConfig.from_mapping(config or {})
        self._client_factory = client_factory
        self._context: AdapterContext | None = None
        self._client: TelegramClient | None = None
        self._groups: dict[str, _MediaGroup] = {}
        self._group_tasks: set[asyncio.Task[None]] = set()
        self._group_lock = asyncio.Lock()
        self._stopping = False

    @property
    def descriptor(self) -> AdapterDescriptor:
        """Return immutable Telegram adapter metadata.

        Returns:
            Telegram adapter descriptor.
        """
        return AdapterDescriptor(
            id="telegram",
            name="Telegram Bot API",
            version="0.4.0",
            api_version=GATEWAY_API_VERSION,
            transport="im",
            capabilities=TELEGRAM_CAPABILITIES,
        )

    async def start(self, context: AdapterContext) -> None:
        """Create Telegram polling/reconnect work and return.

        Args:
            context: Minimal adapter host context.

        Raises:
            ValueError: If the configured token secret is absent.
        """
        token = context.get_secret(self.config.token_env)
        if token is None or not token:
            raise ValueError(
                "required Telegram token environment variable is missing: "
                f"{self.config.token_env}"
            )
        self._context = context
        self._client = self._client_factory(self.config, token)
        self._stopping = False
        context.report_state(AdapterState.DEGRADED, "starting Telegram polling")
        await self._client.start(self._handle_update, context.report_state)

    async def stop(self) -> None:
        """Flush collected albums and stop Telegram transport resources."""
        self._stopping = True
        async with self._group_lock:
            groups = list(self._groups.items())
            self._groups.clear()
        tasks = list(self._group_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._group_tasks.clear()
        for group_id, group in groups:
            await self._emit_media_group(group_id, group.updates)
        if self._client is not None:
            await self._client.stop()
        self._client = None
        self._context = None

    @staticmethod
    def _message(update: Mapping[str, Any]) -> Mapping[str, Any]:
        for field_name in (
            "message",
            "channel_post",
            "edited_message",
            "edited_channel_post",
        ):
            value = update.get(field_name)
            if isinstance(value, Mapping):
                return value
        return {}

    async def _handle_update(self, update: Mapping[str, Any]) -> None:
        if self._stopping:
            return
        message = self._message(update)
        media_group_id = message.get("media_group_id")
        if isinstance(media_group_id, str) and media_group_id:
            await self._queue_media_group(media_group_id, update)
            return
        await self._emit_update(update)

    async def _queue_media_group(
        self,
        media_group_id: str,
        update: Mapping[str, Any],
    ) -> None:
        now = asyncio.get_running_loop().time()
        async with self._group_lock:
            group = self._groups.get(media_group_id)
            if group is None:
                group = _MediaGroup(created_at=now)
                self._groups[media_group_id] = group
            group.updates.append(update)
            if group.task is not None:
                group.task.cancel()
            remaining = self.config.media_group_max_wait - (now - group.created_at)
            delay = max(0.0, min(self.config.media_group_timeout, remaining))
            group.task = asyncio.create_task(
                self._flush_media_group(media_group_id, delay),
                name=f"telegram-media-group-{media_group_id}",
            )
            self._group_tasks.add(group.task)
            group.task.add_done_callback(self._group_tasks.discard)

    async def _flush_media_group(self, media_group_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        async with self._group_lock:
            group = self._groups.pop(media_group_id, None)
        if group is not None:
            await self._emit_media_group(media_group_id, group.updates)

    async def _emit_media_group(
        self,
        media_group_id: str,
        updates: list[Mapping[str, Any]],
    ) -> None:
        events: list[GatewayEvent] = []
        for update in updates:
            event = await self._convert(update)
            if event is not None:
                events.append(event)
        if not events:
            return
        first_event = events[0]
        first_message = IMMessage.from_payload(first_event.payload)
        segments = tuple(
            segment
            for event in events
            for segment in IMMessage.from_payload(event.payload).segments
        )
        merged = IMMessage(
            message_id=first_message.message_id,
            conversation=first_message.conversation,
            sender=first_message.sender,
            segments=segments,
            reply_to=first_message.reply_to,
        )
        metadata = dict(first_event.metadata)
        metadata.update(
            {"media_group_id": media_group_id, "media_group_count": len(events)}
        )
        context = self._context
        if context is not None:
            await context.emit(
                GatewayEvent(
                    id=first_event.id,
                    source=first_event.source,
                    type=first_event.type,
                    payload=merged.to_payload(),
                    timestamp=first_event.timestamp,
                    correlation_id=first_event.correlation_id,
                    metadata=metadata,
                )
            )
            last_update_id = updates[-1].get("update_id")
            if isinstance(last_update_id, int | str):
                await context.state.set("last_update_id", str(last_update_id))

    async def _convert(
        self,
        update: Mapping[str, Any],
    ) -> GatewayEvent | None:
        context = self._context
        client = self._client
        if context is None or client is None:
            return None
        try:
            return await convert_inbound_update(
                self.instance_id,
                update,
                client,
                context.media,
                context.logger(),
            )
        except Exception as exc:
            context.logger().error(
                "telegram_update_conversion_failed",
                exc_info=exc,
                extra={"adapter_id": self.instance_id},
            )
            return None

    async def _emit_update(self, update: Mapping[str, Any]) -> None:
        context = self._context
        event = await self._convert(update)
        if context is None or event is None:
            return
        await context.emit(event)
        update_id = update.get("update_id")
        if isinstance(update_id, int | str):
            await context.state.set("last_update_id", str(update_id))

    async def execute(self, command: GatewayCommand) -> CommandResult:
        """Execute one standard IM operation through Telegram.

        Args:
            command: Command addressed to this adapter.

        Returns:
            Stable command result.
        """
        client = self._client
        context = self._context
        if client is None or context is None:
            return self._failed(
                command,
                GatewayErrorCode.ADAPTER_OFFLINE,
                "Telegram adapter is not started",
                retryable=True,
            )
        try:
            external_id: str | None = None
            if command.type in {IM_MESSAGE_SEND, IM_MESSAGE_REPLY}:
                outbound = IMOutboundMessage.from_payload(command.payload)
                if command.type == IM_MESSAGE_REPLY and outbound.reply_to is None:
                    raise ValueError("reply command requires reply_to")
                external_id = await send_outbound_message(
                    client,
                    command.target.endpoint_id,
                    outbound,
                    context.media,
                )
            elif command.type == IM_MESSAGE_EDIT:
                await edit_message(
                    client,
                    command.target.endpoint_id,
                    IMMessageEdit.from_payload(command.payload),
                )
            elif command.type == IM_MESSAGE_DELETE:
                deletion = IMMessageDelete.from_payload(command.payload)
                chat_id, _thread_id = parse_endpoint(command.target.endpoint_id)
                await client.call(
                    "delete_message",
                    chat_id=chat_id,
                    message_id=int(deletion.message_id),
                )
            elif command.type in {IM_REACTION_ADD, IM_REACTION_REMOVE}:
                await send_reaction(
                    client,
                    command.target.endpoint_id,
                    IMReaction.from_payload(command.payload),
                    remove=command.type == IM_REACTION_REMOVE,
                )
            elif command.type == IM_TYPING_SET:
                await send_typing(
                    client,
                    command.target.endpoint_id,
                    IMTyping.from_payload(command.payload),
                )
            else:
                return self._failed(
                    command,
                    GatewayErrorCode.CAPABILITY_NOT_SUPPORTED,
                    f"capability is not supported: {command.type}",
                )
        except (ValueError, MediaStoreError, TelegramRequestError) as exc:
            return self._failed(
                command,
                GatewayErrorCode.INVALID_COMMAND,
                str(exc),
            )
        except TelegramAuthenticationError as exc:
            context.report_state(AdapterState.FAILED, str(exc))
            return self._failed(command, GatewayErrorCode.AUTH_FAILED, str(exc))
        except TelegramRateLimitError as exc:
            return CommandResult(
                command_id=command.id,
                status="failed",
                error=GatewayError(
                    GatewayErrorCode.RATE_LIMITED,
                    str(exc),
                    retryable=True,
                    details={"retry_after": exc.retry_after},
                ),
            )
        except TelegramNetworkError as exc:
            context.report_state(AdapterState.DEGRADED, str(exc))
            return self._failed(
                command,
                GatewayErrorCode.TRANSPORT_ERROR,
                str(exc),
                retryable=True,
            )
        return CommandResult(
            command_id=command.id,
            status="success",
            external_id=external_id,
        )

    @staticmethod
    def _failed(
        command: GatewayCommand,
        code: GatewayErrorCode,
        message: str,
        *,
        retryable: bool = False,
    ) -> CommandResult:
        return CommandResult(
            command_id=command.id,
            status="failed",
            error=GatewayError(code, message, retryable=retryable),
        )

    async def capabilities(
        self,
        endpoint: EndpointRef | None = None,
    ) -> list[Capability]:
        """Return rich standard Telegram IM capabilities.

        Args:
            endpoint: Optional Telegram endpoint.

        Returns:
            Capabilities or an empty list for foreign endpoints.
        """
        if endpoint is not None and (
            endpoint.adapter_id != self.instance_id or endpoint.transport != "im"
        ):
            return []
        return list(TELEGRAM_CAPABILITIES)

"""Agent-agnostic OneBot v11 TransportAdapter.

Protocol behavior was selectively rewritten from AstrBot's aiocqhttp sources at
upstream commit 0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d under AGPL-3.0-or-later.
AstrBotMessage, AstrMessageEvent, MessageChain, Pipeline, Star, Provider, and Agent
runtime code are intentionally absent.
"""

from collections.abc import Callable, Mapping
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
    TransportAdapter,
)
from gateway.media import MediaStoreError
from gateway.profiles.im import (
    IM_MESSAGE_DELETE,
    IM_MESSAGE_REPLY,
    IM_MESSAGE_SEND,
    IMOutboundMessage,
)

from .capabilities import ONEBOT_CAPABILITIES
from .client import OneBotClient, create_client
from .config import OneBotConfig
from .inbound import convert_inbound_event
from .outbound import convert_outbound_message, parse_endpoint

OneBotClientFactory = Callable[[OneBotConfig, str | None], OneBotClient]


class OneBotAdapter(TransportAdapter):
    """Bridge OneBot v11 events and actions to Gateway contracts.

    Args:
        instance_id: Configured adapter instance identifier.
        config: Adapter-owned configuration.
        client_factory: Optional transport client factory for tests.
    """

    def __init__(
        self,
        instance_id: str,
        config: Mapping[str, Any] | None = None,
        client_factory: OneBotClientFactory = create_client,
    ) -> None:
        if not instance_id or not instance_id.strip():
            raise ValueError("OneBot adapter instance ID must not be empty")
        self.instance_id = instance_id
        self.config = OneBotConfig.from_mapping(config or {})
        self._client_factory = client_factory
        self._context: AdapterContext | None = None
        self._client: OneBotClient | None = None

    @property
    def descriptor(self) -> AdapterDescriptor:
        """Return immutable OneBot adapter metadata.

        Returns:
            OneBot adapter descriptor.
        """
        return AdapterDescriptor(
            adapter_type="onebot",
            name="OneBot v11",
            version="0.3.0",
            api_version=GATEWAY_API_VERSION,
            family="im",
            capabilities=ONEBOT_CAPABILITIES,
        )

    async def start(self, context: AdapterContext) -> None:
        """Create OneBot receive/reconnect tasks and return.

        Args:
            context: Minimal adapter host context.

        Raises:
            ValueError: If a configured token secret is missing.
        """
        token = None
        if self.config.token_env is not None:
            token = context.get_secret(self.config.token_env)
            if token is None or not token:
                raise ValueError(
                    f"required OneBot token environment variable is missing: "
                    f"{self.config.token_env}"
                )
        self._context = context
        self._client = self._client_factory(self.config, token)
        context.report_state(
            AdapterState.DEGRADED,
            "waiting for OneBot WebSocket connection",
        )
        await self._client.start(self._handle_event, context.report_state)

    async def stop(self) -> None:
        """Stop OneBot transport resources."""
        if self._client is not None:
            await self._client.stop()
        self._client = None
        self._context = None

    async def _handle_event(self, raw_event: Mapping[str, Any]) -> None:
        context = self._context
        client = self._client
        if context is None or client is None:
            return
        try:
            event = await convert_inbound_event(
                self.instance_id,
                raw_event,
                client,
                context.media,
                context.logger(),
            )
            await context.emit(event)
            self_id = event.metadata.get("self_id")
            if isinstance(self_id, str) and self_id:
                await context.state.set("self_id", self_id)
            await context.state.set("last_event_id", event.id)
        except Exception as exc:
            context.logger().error(
                "onebot_event_conversion_failed",
                exc_info=exc,
                extra={"adapter_id": self.instance_id},
            )

    async def execute(self, command: GatewayCommand) -> CommandResult:
        """Convert and execute one standard IM command.

        Args:
            command: Command addressed to this adapter.

        Returns:
            Stable command result.
        """
        client = self._client
        context = self._context
        if client is None or context is None:
            return CommandResult(
                command_id=command.id,
                status="failed",
                error=GatewayError(
                    GatewayErrorCode.ADAPTER_OFFLINE,
                    "OneBot adapter is not started",
                    retryable=True,
                ),
            )
        if command.type not in {
            IM_MESSAGE_SEND,
            IM_MESSAGE_REPLY,
            IM_MESSAGE_DELETE,
        }:
            return CommandResult(
                command_id=command.id,
                status="failed",
                error=GatewayError(
                    GatewayErrorCode.CAPABILITY_NOT_SUPPORTED,
                    f"capability is not supported: {command.type}",
                ),
            )
        try:
            routing_params: dict[str, Any] = {}
            self_id = await context.state.get("self_id")
            if isinstance(self_id, str) and self_id.isdigit():
                routing_params["self_id"] = int(self_id)
            if command.type == IM_MESSAGE_DELETE:
                if command.payload.schema != "im.message.delete.v1":
                    raise ValueError("delete command payload schema is invalid")
                message_id = command.payload.data.get("message_id")
                if (
                    not isinstance(message_id, str | int)
                    or not str(message_id).isdigit()
                ):
                    raise ValueError("delete command requires a numeric message_id")
                await client.call_action(
                    "delete_msg",
                    message_id=int(message_id),
                    **routing_params,
                )
                return CommandResult(command_id=command.id, status="success")
            outbound = IMOutboundMessage.from_payload(command.payload)
            if command.type == IM_MESSAGE_REPLY and outbound.reply_to is None:
                raise ValueError("reply command requires reply_to")
            message = await convert_outbound_message(outbound, context.media)
            is_group, conversation_id = parse_endpoint(command.target.endpoint_id)
            action = "send_group_msg" if is_group else "send_private_msg"
            target_name = "group_id" if is_group else "user_id"
            result = await client.call_action(
                action,
                **{target_name: conversation_id},
                message=message,
                **routing_params,
            )
        except (ValueError, MediaStoreError) as exc:
            return CommandResult(
                command_id=command.id,
                status="failed",
                error=GatewayError(
                    GatewayErrorCode.INVALID_COMMAND,
                    str(exc),
                ),
            )
        external_id = result.get("message_id")
        return CommandResult(
            command_id=command.id,
            status="success",
            external_id=None if external_id is None else str(external_id),
        )

    async def capabilities(
        self,
        endpoint: EndpointRef | None = None,
    ) -> list[Capability]:
        """Return conservative OneBot v11 capabilities.

        Args:
            endpoint: Optional OneBot endpoint.

        Returns:
            Standard IM capabilities or an empty list for foreign endpoints.
        """
        if endpoint is not None and (
            endpoint.adapter_id != self.instance_id
            or endpoint.adapter_type != "onebot"
            or endpoint.family != "im"
        ):
            return []
        return list(ONEBOT_CAPABILITIES)

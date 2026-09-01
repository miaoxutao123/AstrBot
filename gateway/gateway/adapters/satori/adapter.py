"""Agent-agnostic Satori TransportAdapter.

Selectively rewritten from AstrBot 4.27.4 at upstream commit
0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d. Agent, plugin, prompt, MessageChain,
global configuration, and data-path dependencies are intentionally absent.
"""

from collections.abc import Callable, Mapping
from typing import Any

from gateway.core import (
    GATEWAY_API_VERSION,
    AdapterContext,
    AdapterDescriptor,
    Capability,
    CommandResult,
    EndpointRef,
    GatewayCommand,
    GatewayError,
    GatewayErrorCode,
    TransportAdapter,
)
from gateway.media import MediaStoreError
from gateway.profiles.im import IM_MESSAGE_REPLY, IM_MESSAGE_SEND, IMOutboundMessage

from .capabilities import SATORI_CAPABILITIES
from .client import SatoriClient, create_client
from .config import SatoriConfig
from .errors import SatoriAuthenticationError, SatoriNetworkError, SatoriRequestError
from .inbound import convert_event
from .outbound import send_message
from .protocol import EVENT, META, READY, SatoriLogin

SatoriClientFactory = Callable[[SatoriConfig, str | None, int], SatoriClient]


class SatoriAdapter(TransportAdapter):
    def __init__(
        self,
        instance_id: str,
        config: Mapping[str, Any] | None = None,
        client_factory: SatoriClientFactory = create_client,
    ) -> None:
        if not instance_id or not instance_id.strip():
            raise ValueError("Satori adapter instance ID must not be empty")
        self.instance_id = instance_id
        self.config = SatoriConfig.from_mapping(config or {})
        self._client_factory = client_factory
        self._context: AdapterContext | None = None
        self._client: SatoriClient | None = None
        self._logins: set[SatoriLogin] = set()

    @property
    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            "satori",
            "Satori Protocol",
            "0.6.0",
            GATEWAY_API_VERSION,
            "im",
            SATORI_CAPABILITIES,
        )

    async def start(self, context: AdapterContext) -> None:
        token = (
            context.get_secret(self.config.token_env) if self.config.token_env else None
        )
        sequence_value = await context.state.get("sequence")
        sequence = (
            sequence_value
            if isinstance(sequence_value, int) and sequence_value >= 0
            else 0
        )
        self._context = context
        self._client = self._client_factory(self.config, token, sequence)
        await self._client.start(self._handle_envelope, context.report_state)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.stop()
        self._client = None
        self._context = None
        self._logins.clear()

    async def _handle_envelope(self, envelope: Mapping[str, Any]) -> None:
        context = self._context
        client = self._client
        if context is None or client is None:
            return
        op = envelope.get("op")
        body = envelope.get("body")
        if not isinstance(body, Mapping):
            return
        sequence = body.get("sn")
        if isinstance(sequence, int):
            await context.state.set("sequence", sequence)
        if op == READY:
            logins = body.get("logins")
            if isinstance(logins, list):
                self._logins = {
                    login
                    for value in logins
                    if isinstance(value, Mapping)
                    and (login := SatoriLogin.from_mapping(value)) is not None
                }
            return
        if op == EVENT:
            event = await convert_event(self.instance_id, body, client, context.media)
            if event is not None:
                await context.emit(event)
        elif op == META:
            return

    async def execute(self, command: GatewayCommand) -> CommandResult:
        client = self._client
        context = self._context
        if client is None or context is None:
            return self._failed(
                command,
                GatewayErrorCode.ADAPTER_OFFLINE,
                "Satori adapter is not started",
                retryable=True,
            )
        if command.type not in {IM_MESSAGE_SEND, IM_MESSAGE_REPLY}:
            return self._failed(
                command,
                GatewayErrorCode.CAPABILITY_NOT_SUPPORTED,
                f"capability is not supported: {command.type}",
            )
        try:
            outbound = IMOutboundMessage.from_payload(command.payload)
            if command.type == IM_MESSAGE_REPLY and outbound.reply_to is None:
                raise ValueError("reply command requires reply_to")
            external_id = await send_message(
                client, command.target.endpoint_id, outbound, context.media
            )
        except (ValueError, MediaStoreError, SatoriRequestError) as exc:
            return self._failed(command, GatewayErrorCode.INVALID_COMMAND, str(exc))
        except SatoriAuthenticationError as exc:
            return self._failed(command, GatewayErrorCode.AUTH_FAILED, str(exc))
        except SatoriNetworkError as exc:
            return self._failed(
                command, GatewayErrorCode.TRANSPORT_ERROR, str(exc), retryable=True
            )
        return CommandResult(
            command_id=command.id,
            status="success",
            external_id=external_id,
        )

    async def capabilities(
        self, endpoint: EndpointRef | None = None
    ) -> list[Capability]:
        if endpoint is not None and (
            endpoint.family != "im"
            or endpoint.adapter_type != "satori"
            or endpoint.adapter_id != self.instance_id
        ):
            return []
        return list(SATORI_CAPABILITIES)

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

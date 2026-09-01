"""Tencent QQ Official Bot gateway WebSocket TransportAdapter.

Selectively rewritten from AstrBot 4.27.4 commit
0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d. This is independent from OneBot v11
and contains no Agent, plugin, prompt, MessageChain, or AstrBot runtime code.
"""

import json
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
    GatewayEvent,
    Payload,
    TransportAdapter,
)
from gateway.media import MediaStoreError
from gateway.profiles.im import IM_MESSAGE_REPLY, IM_MESSAGE_SEND, IMOutboundMessage

from ..common.capabilities import QQ_OFFICIAL_CAPABILITIES, endpoint_capabilities
from ..common.errors import (
    QQOfficialAuthenticationError,
    QQOfficialDeliveryError,
    QQOfficialNetworkError,
    QQOfficialRateLimitError,
    QQOfficialRequestError,
    QQOfficialTimeoutError,
)
from ..common.inbound import convert_event
from ..common.models import QQOfficialEndpoint
from ..common.outbound import send_message
from .client import QQOfficialWebSocketClient, TencentGatewayClient
from .config import QQOfficialWebSocketConfig

TOKEN_KEY = "access_token"
SESSION_KEY = "gateway_session"
ClientFactory = Callable[..., QQOfficialWebSocketClient]


class QQOfficialWebSocketAdapter(TransportAdapter):
    def __init__(
        self,
        instance_id: str,
        config: Mapping[str, Any] | None = None,
        client_factory: ClientFactory = TencentGatewayClient,
    ) -> None:
        if not instance_id or not instance_id.strip():
            raise ValueError("QQ Official adapter instance ID must not be empty")
        self.instance_id = instance_id
        self.config = QQOfficialWebSocketConfig.from_mapping(config or {})
        self._client_factory = client_factory
        self._context: AdapterContext | None = None
        self._client: QQOfficialWebSocketClient | None = None

    @property
    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            "qq_official",
            "QQ Official WebSocket",
            "0.6.0",
            GATEWAY_API_VERSION,
            "im",
            QQ_OFFICIAL_CAPABILITIES,
        )

    async def start(self, context: AdapterContext) -> None:
        app_id = context.get_secret(self.config.common.app_id_env)
        secret = context.get_secret(self.config.common.secret_env)
        if not app_id or not secret:
            raise ValueError("QQ Official app_id or secret is missing")
        token, expires_at = await self._restore_token(context)
        session = await context.state.get(SESSION_KEY)
        session_value = session if isinstance(session, Mapping) else {}
        session_id = (
            session_value.get("session_id")
            if isinstance(session_value.get("session_id"), str)
            else None
        )
        sequence = (
            session_value.get("sequence")
            if isinstance(session_value.get("sequence"), int)
            else None
        )
        resume_url = (
            session_value.get("resume_url")
            if isinstance(session_value.get("resume_url"), str)
            else None
        )
        self._context = context
        self._client = self._client_factory(
            self.config,
            app_id,
            secret,
            token,
            expires_at,
            session_id,
            sequence,
            resume_url,
        )
        await self._client.start(
            self._dispatch, context.report_state, self._save_token, self._save_session
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.stop()
        self._client = None
        self._context = None

    async def _restore_token(self, context: AdapterContext) -> tuple[str | None, float]:
        value = await context.secrets.get(TOKEN_KEY)
        if not value:
            return None, 0
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("stored QQ Official access credential is invalid") from exc
        if not isinstance(parsed, Mapping) or not isinstance(parsed.get("token"), str):
            raise ValueError("stored QQ Official access credential is invalid")
        expiry = parsed.get("expires_at")
        return parsed["token"], float(expiry) if isinstance(expiry, int | float) else 0

    async def _save_token(self, token: str, expires_at: float) -> None:
        if self._context is not None:
            await self._context.secrets.set(
                TOKEN_KEY,
                json.dumps(
                    {"token": token, "expires_at": expires_at}, separators=(",", ":")
                ),
            )

    async def _save_session(
        self, session_id: str | None, sequence: int | None, resume_url: str | None
    ) -> None:
        if self._context is None:
            return
        if session_id is None:
            await self._context.state.delete(SESSION_KEY)
            return
        await self._context.state.set(
            SESSION_KEY,
            {"session_id": session_id, "sequence": sequence, "resume_url": resume_url},
        )

    async def _dispatch(self, event_type: str, data: Mapping[str, Any]) -> None:
        context = self._context
        client = self._client
        if context is None or client is None:
            return
        event = await convert_event(
            self.instance_id, event_type, data, client, context.media
        )
        if event is None:
            event = GatewayEvent(
                source=EndpointRef(
                    "im", "qq_official", self.instance_id, f"event:{event_type.lower()}"
                ),
                type="qq_official.event",
                payload=Payload(
                    "qq_official.event.v1",
                    {"event_type": event_type, "data": dict(data)},
                ),
                metadata={"qq_event_type": event_type},
            )
        await context.emit(event)

    async def execute(self, command: GatewayCommand) -> CommandResult:
        client = self._client
        context = self._context
        if client is None or context is None:
            return self._failed(
                command,
                GatewayErrorCode.ADAPTER_OFFLINE,
                "QQ Official adapter is not started",
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
                command.target.endpoint_id, outbound, client, context.media
            )
        except (ValueError, MediaStoreError, QQOfficialRequestError) as exc:
            return self._failed(command, GatewayErrorCode.INVALID_COMMAND, str(exc))
        except QQOfficialAuthenticationError as exc:
            return self._failed(command, GatewayErrorCode.AUTH_FAILED, str(exc))
        except QQOfficialRateLimitError as exc:
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
        except QQOfficialTimeoutError as exc:
            return self._failed(
                command, GatewayErrorCode.TIMEOUT, str(exc), retryable=True
            )
        except QQOfficialDeliveryError as exc:
            return self._failed(
                command, GatewayErrorCode.DELIVERY_FAILED, str(exc), retryable=True
            )
        except QQOfficialNetworkError as exc:
            return self._failed(
                command, GatewayErrorCode.TRANSPORT_ERROR, str(exc), retryable=True
            )
        return CommandResult(
            command_id=command.id, status="success", external_id=external_id
        )

    async def capabilities(
        self, endpoint: EndpointRef | None = None
    ) -> list[Capability]:
        if endpoint is None:
            return list(QQ_OFFICIAL_CAPABILITIES)
        if (
            endpoint.family != "im"
            or endpoint.adapter_type != "qq_official"
            or endpoint.adapter_id != self.instance_id
        ):
            return []
        try:
            scene = QQOfficialEndpoint.decode(endpoint.endpoint_id).scene
        except ValueError:
            return []
        return endpoint_capabilities(scene)

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


def create_adapter(
    instance_id: str, config: Mapping[str, Any] | None = None
) -> QQOfficialWebSocketAdapter:
    return QQOfficialWebSocketAdapter(instance_id, config)

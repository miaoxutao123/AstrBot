"""Agent-agnostic Weixin OC TransportAdapter composition.

Protocol behavior is selectively rewritten from AstrBot's ``weixin_oc`` source.
AstrBot configuration, data paths, plugins, prompts, and agent runtime objects are
intentionally absent.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from gateway.core import (
    GATEWAY_API_VERSION,
    AdapterAuthInfo,
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
from gateway.profiles.im import (
    IM_MESSAGE_SEND,
    IM_TYPING_SET,
    IMOutboundMessage,
    IMTyping,
)

from .auth import WeixinAuthFlow
from .capabilities import WEIXIN_CAPABILITIES
from .client import WeixinClient, create_client
from .config import WeixinConfig
from .errors import WeixinAuthenticationError, WeixinError, WeixinRequestError
from .inbound import convert_inbound_message
from .outbound import send_message, send_typing
from .session import WeixinSession, WeixinSessionStore, integer_value, string_value

WeixinClientFactory = Callable[[WeixinConfig], WeixinClient]
SESSION_TIMEOUT_ERRCODE = -14


class WeixinAdapter(TransportAdapter):
    """Compose Weixin auth, session, polling, conversion, and command services."""

    def __init__(
        self,
        instance_id: str,
        config: Mapping[str, Any] | None = None,
        client_factory: WeixinClientFactory = create_client,
    ) -> None:
        if not instance_id or not instance_id.strip():
            raise ValueError("Weixin adapter instance ID must not be empty")
        self.instance_id = instance_id
        self.config = WeixinConfig.from_mapping(config or {})
        self._client_factory = client_factory
        self._client: WeixinClient | None = None
        self._context: AdapterContext | None = None
        self._session = WeixinSession()
        self._session_store: WeixinSessionStore | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._auth = WeixinAuthFlow(instance_id, self._stop, self._login_confirmed)

    @property
    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            adapter_type="weixin",
            name="Weixin OC",
            version="0.5.1",
            api_version=GATEWAY_API_VERSION,
            family="im",
            capabilities=WEIXIN_CAPABILITIES,
        )

    async def start(self, context: AdapterContext) -> None:
        """Restore session state, compose protocol services, and return."""
        self._context = context
        self._stop.clear()
        self._session_store = WeixinSessionStore(context)
        self._session = await self._session_store.restore()
        if self._session.base_url:
            self.config = replace(
                self.config, base_url=self._session.base_url.rstrip("/")
            )
        self._client = self._client_factory(self.config)
        if self._session.token:
            self._auth.authenticated()
            self._start_receive_task()
            context.report_state(AdapterState.RUNNING, None)
        else:
            self._auth.logged_out()
            context.report_state(
                AdapterState.DEGRADED, "Weixin authentication required"
            )

    async def stop(self) -> None:
        """Cancel authentication/polling tasks and close HTTP resources."""
        self._stop.set()
        await self._auth.stop()
        if self._receive_task is not None:
            self._receive_task.cancel()
            await asyncio.gather(self._receive_task, return_exceptions=True)
        self._receive_task = None
        if self._client is not None:
            await self._client.close()
        self._client = None
        self._session_store = None
        self._context = None

    async def auth_info(self) -> AdapterAuthInfo:
        return self._auth.info()

    async def start_auth(self) -> AdapterAuthInfo:
        return await self._auth.start(
            self._client, self.config, bool(self._session.token)
        )

    async def cancel_auth(self) -> AdapterAuthInfo:
        return await self._auth.cancel(bool(self._session.token))

    async def _login_confirmed(
        self, token: str, account_id: str | None, base_url: str | None
    ) -> None:
        context = self._context
        store = self._session_store
        client = self._client
        if context is None or store is None or client is None:
            raise WeixinRequestError("Weixin adapter is not started")
        self._session.token = token
        self._session.account_id = account_id
        if base_url and base_url.rstrip("/") != self.config.base_url:
            await client.close()
            self.config = replace(self.config, base_url=base_url.rstrip("/"))
            self._client = self._client_factory(self.config)
        self._session.base_url = self.config.base_url
        await store.save(self._session, self.config)
        context.report_state(AdapterState.RUNNING, None)
        self._start_receive_task()

    def _start_receive_task(self) -> None:
        if self._receive_task is None or self._receive_task.done():
            self._receive_task = asyncio.create_task(
                self._receive_loop(), name=f"weixin-poll-{self.instance_id}"
            )

    async def _receive_loop(self) -> None:
        delay = 1.0
        while not self._stop.is_set() and self._session.token:
            client = self._client
            context = self._context
            store = self._session_store
            if client is None or context is None or store is None:
                return
            try:
                data = await client.request(
                    "POST",
                    "ilink/bot/getupdates",
                    payload={
                        "base_info": {"channel_version": "astrbot-gateway"},
                        "get_updates_buf": self._session.cursor,
                    },
                    token=self._session.token,
                    timeout=self.config.long_poll_timeout,
                )
                if integer_value(data.get("errcode")) == SESSION_TIMEOUT_ERRCODE:
                    await self._invalidate_session("Weixin session token expired")
                    return
                if integer_value(data.get("ret")) or integer_value(data.get("errcode")):
                    raise WeixinRequestError("Weixin update poll was rejected")
                cursor = string_value(data.get("get_updates_buf"))
                if cursor:
                    self._session.cursor = cursor
                await self._emit_updates(data.get("msgs"))
                await store.save(self._session, self.config)
                context.report_state(AdapterState.RUNNING, None)
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except WeixinAuthenticationError as exc:
                await self._invalidate_session(str(exc))
                return
            except WeixinError:
                context.report_state(
                    AdapterState.DEGRADED, "Weixin polling failed; reconnecting"
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, self.config.reconnect_max_delay)

    async def _emit_updates(self, messages: object) -> None:
        context = self._context
        client = self._client
        if context is None or client is None or not isinstance(messages, list):
            return
        for message in messages:
            if not isinstance(message, Mapping):
                continue
            try:
                converted = await convert_inbound_message(
                    self.instance_id, message, client, context.media
                )
                if converted is None:
                    continue
                if converted.context_token:
                    self._session.context_tokens[converted.user_id] = (
                        converted.context_token
                    )
                await context.emit(converted.event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                context.logger().error(
                    "weixin_message_conversion_failed",
                    exc_info=exc,
                    extra={"adapter_id": self.instance_id},
                )

    async def execute(self, command: GatewayCommand) -> CommandResult:
        """Dispatch standard IM operations to the outbound converter."""
        client = self._client
        context = self._context
        if not self._session.token or client is None or context is None:
            return self._failed(
                command, GatewayErrorCode.AUTH_FAILED, "Weixin authentication required"
            )
        try:
            if command.type == IM_MESSAGE_SEND:
                external_id = await send_message(
                    command.target.endpoint_id,
                    IMOutboundMessage.from_payload(command.payload),
                    client,
                    context.media,
                    self._session,
                )
            elif command.type == IM_TYPING_SET:
                typing = IMTyping.from_payload(command.payload)
                await send_typing(
                    command.target.endpoint_id,
                    typing.action != "cancel",
                    client,
                    self._session,
                )
                external_id = None
            else:
                return self._failed(
                    command,
                    GatewayErrorCode.CAPABILITY_NOT_SUPPORTED,
                    f"capability is not supported: {command.type}",
                )
        except (ValueError, WeixinRequestError) as exc:
            return self._failed(command, GatewayErrorCode.INVALID_COMMAND, str(exc))
        except WeixinAuthenticationError as exc:
            await self._invalidate_session(str(exc))
            return self._failed(command, GatewayErrorCode.AUTH_FAILED, str(exc))
        except WeixinError as exc:
            context.report_state(AdapterState.DEGRADED, str(exc))
            return self._failed(
                command, GatewayErrorCode.TRANSPORT_ERROR, str(exc), retryable=True
            )
        return CommandResult(
            command_id=command.id, status="success", external_id=external_id
        )

    async def _invalidate_session(self, reason: str) -> None:
        if self._session_store is not None:
            await self._session_store.invalidate(self._session)
        self._auth.logged_out(reason)
        if self._context is not None:
            self._context.report_state(AdapterState.DEGRADED, reason)

    async def capabilities(
        self, endpoint: EndpointRef | None = None
    ) -> list[Capability]:
        if endpoint is not None and (
            endpoint.adapter_id != self.instance_id
            or endpoint.adapter_type != "weixin"
            or endpoint.family != "im"
        ):
            return []
        return list(WEIXIN_CAPABILITIES)

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

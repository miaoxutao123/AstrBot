"""Agent-agnostic Weixin OC transport adapter.

The protocol behavior is selectively rewritten from AstrBot's ``weixin_oc``
source. AstrBot configuration, data paths, plugins, prompts, and agent runtime
objects are intentionally absent.
"""

import asyncio
import base64
import hashlib
import mimetypes
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from gateway.core import (
    GATEWAY_API_VERSION,
    AdapterAuthInfo,
    AdapterAuthStatus,
    AdapterContext,
    AdapterDescriptor,
    AdapterState,
    AuthChallenge,
    Capability,
    CommandResult,
    EndpointRef,
    GatewayCommand,
    GatewayError,
    GatewayErrorCode,
    GatewayEvent,
    TransportAdapter,
)
from gateway.profiles.im import (
    IM_MESSAGE_SEND,
    IM_TYPING_SET,
    IMConversation,
    IMMessage,
    IMOutboundMessage,
    IMSegment,
    IMSender,
    IMTyping,
)

from .capabilities import WEIXIN_CAPABILITIES
from .client import WeixinClient, create_client
from .config import WeixinConfig
from .errors import WeixinAuthenticationError, WeixinError, WeixinRequestError

WeixinClientFactory = Callable[[WeixinConfig], WeixinClient]
SESSION_KEY = "session"
SESSION_TIMEOUT_ERRCODE = -14


class WeixinAdapter(TransportAdapter):
    """Bridge Weixin OC QR authentication, polling, and IM operations."""

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
        self._token: str | None = None
        self._account_id: str | None = None
        self._cursor = ""
        self._context_tokens: dict[str, str] = {}
        self._auth_status = AdapterAuthStatus.LOGGED_OUT
        self._challenge: AuthChallenge | None = None
        self._auth_reason: str | None = None
        self._qr_code: str | None = None
        self._auth_task: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._auth_lock = asyncio.Lock()
        self._stop = asyncio.Event()

    @property
    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            id="weixin",
            name="Weixin OC",
            version="0.5.0",
            api_version=GATEWAY_API_VERSION,
            transport="im",
            capabilities=WEIXIN_CAPABILITIES,
        )

    async def start(self, context: AdapterContext) -> None:
        self._context = context
        self._stop.clear()
        await self._restore_session()
        self._client = self._client_factory(self.config)
        if self._token:
            self._auth_status = AdapterAuthStatus.AUTHENTICATED
            self._start_receive_task()
            context.report_state(AdapterState.RUNNING, None)
        else:
            self._auth_status = AdapterAuthStatus.LOGGED_OUT
            context.report_state(
                AdapterState.DEGRADED, "Weixin authentication required"
            )

    async def stop(self) -> None:
        self._stop.set()
        tasks = [task for task in (self._auth_task, self._receive_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._auth_task = None
        self._receive_task = None
        if self._client is not None:
            await self._client.close()
        self._client = None
        self._context = None

    async def auth_info(self) -> AdapterAuthInfo:
        return AdapterAuthInfo(self._auth_status, self._challenge, self._auth_reason)

    async def start_auth(self) -> AdapterAuthInfo:
        async with self._auth_lock:
            if self._context is None or self._client is None:
                return AdapterAuthInfo(
                    AdapterAuthStatus.FAILED, reason="adapter is not started"
                )
            if self._token:
                return AdapterAuthInfo(AdapterAuthStatus.AUTHENTICATED)
            if self._auth_task is not None and not self._auth_task.done():
                return await self.auth_info()
            try:
                data = await self._client.request(
                    "GET",
                    "ilink/bot/get_bot_qrcode",
                    params={"bot_type": self.config.bot_type},
                    timeout=15.0,
                )
                qr_code = _string(data.get("qrcode"))
                qr_uri = _string(data.get("qrcode_img_content"))
                if not qr_code or not qr_uri:
                    raise WeixinRequestError("Weixin QR response is incomplete")
            except WeixinError as exc:
                self._set_auth(AdapterAuthStatus.FAILED, reason=str(exc))
                return await self.auth_info()
            self._qr_code = qr_code
            self._set_auth(
                AdapterAuthStatus.WAITING_USER,
                AuthChallenge(qr_uri=qr_uri, instructions="使用手机微信扫码并确认登录"),
            )
            self._auth_task = asyncio.create_task(
                self._poll_auth(), name=f"weixin-auth-{self.instance_id}"
            )
            return await self.auth_info()

    async def cancel_auth(self) -> AdapterAuthInfo:
        async with self._auth_lock:
            if self._auth_task is not None:
                self._auth_task.cancel()
                await asyncio.gather(self._auth_task, return_exceptions=True)
            self._auth_task = None
            self._qr_code = None
            if not self._token:
                self._set_auth(AdapterAuthStatus.LOGGED_OUT)
            return await self.auth_info()

    def _set_auth(
        self,
        status: AdapterAuthStatus,
        challenge: AuthChallenge | None = None,
        reason: str | None = None,
    ) -> None:
        self._auth_status = status
        self._challenge = challenge
        self._auth_reason = reason

    async def _poll_auth(self) -> None:
        client = self._client
        context = self._context
        if client is None or context is None or self._qr_code is None:
            return
        try:
            while not self._stop.is_set():
                data = await client.request(
                    "GET",
                    "ilink/bot/get_qrcode_status",
                    params={"qrcode": self._qr_code},
                    timeout=self.config.long_poll_timeout,
                    headers={"iLink-App-ClientVersion": "1"},
                )
                status = _string(data.get("status")) or "wait"
                if status == "confirmed":
                    token = _string(data.get("bot_token"))
                    if not token:
                        raise WeixinAuthenticationError(
                            "Weixin login did not return a token"
                        )
                    self._token = token
                    self._account_id = _string(data.get("ilink_bot_id")) or None
                    base_url = _string(data.get("baseurl"))
                    if base_url and base_url.rstrip("/") != self.config.base_url:
                        await client.close()
                        self.config = replace(
                            self.config, base_url=base_url.rstrip("/")
                        )
                        self._client = self._client_factory(self.config)
                    await self._save_session()
                    self._set_auth(AdapterAuthStatus.AUTHENTICATED)
                    context.report_state(AdapterState.RUNNING, None)
                    self._start_receive_task()
                    return
                if status == "expired":
                    self._set_auth(
                        AdapterAuthStatus.EXPIRED, reason="Weixin QR code expired"
                    )
                    return
                if status in {"cancel", "canceled", "denied"}:
                    self._set_auth(
                        AdapterAuthStatus.FAILED, reason="Weixin login was cancelled"
                    )
                    return
                await asyncio.sleep(self.config.qr_poll_interval)
        except asyncio.CancelledError:
            raise
        except WeixinError as exc:
            self._set_auth(AdapterAuthStatus.FAILED, reason=str(exc))
        finally:
            self._qr_code = None

    def _start_receive_task(self) -> None:
        if self._receive_task is None or self._receive_task.done():
            self._receive_task = asyncio.create_task(
                self._receive_loop(), name=f"weixin-poll-{self.instance_id}"
            )

    async def _receive_loop(self) -> None:
        delay = 1.0
        while not self._stop.is_set() and self._token:
            client = self._client
            context = self._context
            if client is None or context is None:
                return
            try:
                data = await client.request(
                    "POST",
                    "ilink/bot/getupdates",
                    payload={
                        "base_info": {"channel_version": "astrbot-gateway"},
                        "get_updates_buf": self._cursor,
                    },
                    token=self._token,
                    timeout=self.config.long_poll_timeout,
                )
                if _integer(data.get("errcode")) == SESSION_TIMEOUT_ERRCODE:
                    await self._invalidate_session("Weixin session token expired")
                    return
                if _integer(data.get("ret")) or _integer(data.get("errcode")):
                    raise WeixinRequestError("Weixin update poll was rejected")
                cursor = _string(data.get("get_updates_buf"))
                if cursor:
                    self._cursor = cursor
                messages = data.get("msgs", [])
                if isinstance(messages, list):
                    for message in messages:
                        if isinstance(message, Mapping):
                            try:
                                await self._emit_message(message)
                            except asyncio.CancelledError:
                                raise
                            except Exception as exc:
                                context.logger().error(
                                    "weixin_message_conversion_failed",
                                    exc_info=exc,
                                    extra={"adapter_id": self.instance_id},
                                )
                await self._save_session()
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

    async def _emit_message(self, raw: Mapping[str, Any]) -> None:
        context = self._context
        client = self._client
        if context is None or client is None:
            return
        sender = _string(raw.get("from_user_id"))
        if not sender:
            return
        context_token = _string(raw.get("context_token"))
        if context_token:
            self._context_tokens[sender] = context_token
        segments: list[IMSegment] = []
        reply_to: str | None = None
        items = raw.get("item_list", [])
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                segment = await self._inbound_segment(item)
                if segment is not None:
                    segments.append(segment)
                ref = item.get("ref_msg")
                if isinstance(ref, Mapping):
                    referenced = ref.get("message_item")
                    if isinstance(referenced, Mapping):
                        reply_to = _string(
                            referenced.get("message_id") or referenced.get("msg_id")
                        )
                        reference_time = _string(referenced.get("create_time_ms"))
                        if not reply_to and reference_time:
                            reply_to = f"weixin_ref_{reference_time}"
        if not segments:
            segments.append(IMSegment.raw("weixin", "message", raw))
        message_id = (
            _string(raw.get("message_id") or raw.get("msg_id")) or uuid.uuid4().hex
        )
        timestamp_value = (
            raw.get("create_time_ms") or raw.get("create_time") or time.time()
        )
        timestamp = (
            float(timestamp_value) / 1000
            if isinstance(timestamp_value, int | float)
            and timestamp_value > 1_000_000_000_000
            else float(timestamp_value)
        )
        profile = IMMessage(
            message_id,
            IMConversation("private", sender),
            IMSender(sender, sender),
            tuple(segments),
            reply_to,
        )
        await context.emit(
            GatewayEvent(
                id=f"evt_weixin_{self.instance_id}_{message_id}",
                source=EndpointRef("im", self.instance_id, sender),
                type="im.message.received",
                payload=profile.to_payload(),
                timestamp=timestamp,
                metadata={"platform": "weixin"},
            )
        )

    async def _inbound_segment(self, item: Mapping[str, Any]) -> IMSegment | None:
        item_type = _integer(item.get("type"))
        if item_type == 1:
            text_item = item.get("text_item")
            text = (
                _string(text_item.get("text")) if isinstance(text_item, Mapping) else ""
            )
            return IMSegment.text(text) if text else None
        names = {
            2: ("image_item", "image", "image.jpg"),
            3: ("voice_item", "audio", "voice.silk"),
            4: ("file_item", "file", "file.bin"),
            5: ("video_item", "video", "video.mp4"),
        }
        selected = names.get(item_type)
        if selected is None or self._client is None or self._context is None:
            return None
        field, segment_type, fallback = selected
        value = item.get(field)
        if not isinstance(value, Mapping):
            return None
        media = value.get("media")
        if not isinstance(media, Mapping):
            return None
        query = _string(media.get("encrypt_query_param"))
        key = _string(media.get("aes_key")) or None
        if item_type == 2 and not key:
            raw_key = _string(value.get("aeskey"))
            if raw_key:
                key = base64.b64encode(bytes.fromhex(raw_key)).decode()
        if not query:
            return None
        content = await self._client.download(
            query,
            key,
            self._context.media.max_upload_size,
        )
        filename = _string(value.get("file_name")) or fallback
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        metadata = await self._context.media.put(content, mime_type, filename)
        return IMSegment.media(segment_type, metadata)

    async def execute(self, command: GatewayCommand) -> CommandResult:
        if not self._token or self._client is None or self._context is None:
            return self._failed(
                command, GatewayErrorCode.AUTH_FAILED, "Weixin authentication required"
            )
        try:
            if command.type == IM_MESSAGE_SEND:
                outbound = IMOutboundMessage.from_payload(command.payload)
                external_id = await self._send(command.target.endpoint_id, outbound)
            elif command.type == IM_TYPING_SET:
                typing = IMTyping.from_payload(command.payload)
                await self._send_typing(
                    command.target.endpoint_id, typing.action != "cancel"
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
            self._context.report_state(AdapterState.DEGRADED, str(exc))
            return self._failed(
                command, GatewayErrorCode.TRANSPORT_ERROR, str(exc), retryable=True
            )
        return CommandResult(
            command_id=command.id, status="success", external_id=external_id
        )

    async def _send(self, user_id: str, outbound: IMOutboundMessage) -> str:
        client = self._client
        if client is None:
            raise WeixinRequestError("Weixin client is not started")
        context_token = self._context_tokens.get(user_id)
        if not context_token:
            raise WeixinRequestError(
                "Weixin context token is unavailable; receive a message from this user first"
            )
        items: list[dict[str, Any]] = []
        if outbound.reply_to:
            raise ValueError("Weixin outbound reply is not supported")
        for segment in outbound.segments:
            if segment.type == "text":
                items.append({"type": 1, "text_item": {"text": segment.data["text"]}})
            elif segment.type in {"image", "video", "file"}:
                items.append(await self._prepare_media(user_id, segment))
            else:
                raise ValueError(f"Weixin segment is unsupported: {segment.type}")
        client_id = uuid.uuid4().hex
        result = await client.request(
            "POST",
            "ilink/bot/sendmessage",
            payload={
                "base_info": {"channel_version": "astrbot-gateway"},
                "msg": {
                    "from_user_id": "",
                    "to_user_id": user_id,
                    "client_id": client_id,
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": items,
                },
            },
            token=self._token,
        )
        self._check_result(result)
        return client_id

    async def _prepare_media(self, user_id: str, segment: IMSegment) -> dict[str, Any]:
        assert self._context is not None and self._client is not None
        media = segment.data.get("media")
        if not isinstance(media, Mapping):
            raise ValueError("media segment is invalid")
        content = await self._context.media.get(_string(media.get("media_id")))
        raw = content.data
        key = uuid.uuid4().bytes
        file_key = uuid.uuid4().hex
        upload_type, item_type, field, size_field = {
            "image": (1, 2, "image_item", "mid_size"),
            "video": (2, 5, "video_item", "video_size"),
            "file": (3, 4, "file_item", "len"),
        }[segment.type]
        result = await self._client.request(
            "POST",
            "ilink/bot/getuploadurl",
            payload={
                "filekey": file_key,
                "media_type": upload_type,
                "to_user_id": user_id,
                "rawsize": len(raw),
                "rawfilemd5": hashlib.md5(raw).hexdigest(),
                "filesize": len(raw) + (16 - len(raw) % 16),
                "no_need_thumb": True,
                "aeskey": key.hex(),
                "base_info": {"channel_version": "astrbot-gateway"},
            },
            token=self._token,
        )
        query = await self._client.upload(
            _string(result.get("upload_full_url")),
            _string(result.get("upload_param")),
            file_key,
            key,
            raw,
        )
        media_payload = {
            "encrypt_query_param": query,
            "aes_key": base64.b64encode(key.hex().encode()).decode(),
            "encrypt_type": 1,
        }
        item_value: dict[str, Any] = {
            "media": media_payload,
            size_field: str(len(raw))
            if segment.type == "file"
            else len(raw) + (16 - len(raw) % 16),
        }
        if segment.type == "file":
            item_value["file_name"] = content.metadata.filename
        return {"type": item_type, field: item_value}

    async def _send_typing(self, user_id: str, active: bool) -> None:
        client = self._client
        if client is None:
            raise WeixinRequestError("Weixin client is not started")
        context_token = self._context_tokens.get(user_id)
        if not context_token:
            raise WeixinRequestError("Weixin context token is unavailable")
        config = await client.request(
            "POST",
            "ilink/bot/getconfig",
            payload={
                "ilink_user_id": user_id,
                "context_token": context_token,
                "base_info": {"channel_version": "astrbot-gateway"},
            },
            token=self._token,
        )
        ticket = _string(config.get("typing_ticket"))
        if not ticket:
            raise WeixinRequestError("Weixin typing ticket is unavailable")
        result = await client.request(
            "POST",
            "ilink/bot/sendtyping",
            payload={
                "ilink_user_id": user_id,
                "typing_ticket": ticket,
                "status": 1 if active else 2,
                "base_info": {"channel_version": "astrbot-gateway"},
            },
            token=self._token,
        )
        self._check_result(result)

    @staticmethod
    def _check_result(result: Mapping[str, Any]) -> None:
        errcode = _integer(result.get("errcode"))
        if errcode == SESSION_TIMEOUT_ERRCODE:
            raise WeixinAuthenticationError("Weixin session token expired")
        if _integer(result.get("ret")) or errcode:
            raise WeixinRequestError("Weixin request was rejected")

    async def _restore_session(self) -> None:
        assert self._context is not None
        value = await self._context.state.get(SESSION_KEY)
        if not isinstance(value, Mapping):
            return
        self._token = _string(value.get("token")) or None
        self._account_id = _string(value.get("account_id")) or None
        self._cursor = _string(value.get("cursor"))
        base_url = _string(value.get("base_url"))
        if base_url:
            self.config = replace(self.config, base_url=base_url.rstrip("/"))
        tokens = value.get("context_tokens")
        if isinstance(tokens, Mapping):
            self._context_tokens = {
                _string(key): _string(token)
                for key, token in tokens.items()
                if _string(key) and _string(token)
            }

    async def _save_session(self) -> None:
        if self._context is None or not self._token:
            return
        await self._context.state.set(
            SESSION_KEY,
            {
                "token": self._token,
                "account_id": self._account_id,
                "base_url": self.config.base_url,
                "cursor": self._cursor,
                "context_tokens": dict(self._context_tokens),
            },
        )

    async def _invalidate_session(self, reason: str) -> None:
        self._token = None
        self._account_id = None
        self._cursor = ""
        self._context_tokens.clear()
        self._set_auth(AdapterAuthStatus.LOGGED_OUT, reason=reason)
        if self._context is not None:
            await self._context.state.delete(SESSION_KEY)
            self._context.report_state(AdapterState.DEGRADED, reason)

    async def capabilities(
        self, endpoint: EndpointRef | None = None
    ) -> list[Capability]:
        if endpoint is not None and (
            endpoint.adapter_id != self.instance_id or endpoint.transport != "im"
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


def _string(value: object) -> str:
    return (
        value.strip()
        if isinstance(value, str)
        else str(value).strip()
        if isinstance(value, int)
        else ""
    )


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float | str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0

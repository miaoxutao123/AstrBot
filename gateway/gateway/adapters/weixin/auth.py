"""Weixin QR authentication protocol state machine."""

import asyncio
from collections.abc import Awaitable, Callable

from gateway.core import AdapterAuthInfo, AdapterAuthStatus, AuthChallenge

from .client import WeixinClient
from .config import WeixinConfig
from .errors import WeixinAuthenticationError, WeixinError, WeixinRequestError
from .session import string_value

ConfirmationHandler = Callable[[str, str | None, str | None], Awaitable[None]]


class WeixinAuthFlow:
    """Acquire and poll QR challenges without depending on Gateway API routes."""

    def __init__(
        self, instance_id: str, stop: asyncio.Event, on_confirmed: ConfirmationHandler
    ) -> None:
        self._instance_id = instance_id
        self._stop = stop
        self._on_confirmed = on_confirmed
        self._status = AdapterAuthStatus.LOGGED_OUT
        self._challenge: AuthChallenge | None = None
        self._reason: str | None = None
        self._qr_code: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def info(self) -> AdapterAuthInfo:
        return AdapterAuthInfo(self._status, self._challenge, self._reason)

    def authenticated(self) -> None:
        self._set(AdapterAuthStatus.AUTHENTICATED)

    def logged_out(self, reason: str | None = None) -> None:
        self._set(AdapterAuthStatus.LOGGED_OUT, reason=reason)

    async def start(
        self, client: WeixinClient | None, config: WeixinConfig, authenticated: bool
    ) -> AdapterAuthInfo:
        async with self._lock:
            if client is None:
                return AdapterAuthInfo(
                    AdapterAuthStatus.FAILED, reason="adapter is not started"
                )
            if authenticated:
                return AdapterAuthInfo(AdapterAuthStatus.AUTHENTICATED)
            if self._task is not None and not self._task.done():
                return self.info()
            try:
                data = await client.request(
                    "GET",
                    "ilink/bot/get_bot_qrcode",
                    params={"bot_type": config.bot_type},
                    timeout=15.0,
                )
                qr_code = string_value(data.get("qrcode"))
                qr_uri = string_value(data.get("qrcode_img_content"))
                if not qr_code or not qr_uri:
                    raise WeixinRequestError("Weixin QR response is incomplete")
            except WeixinError as exc:
                self._set(AdapterAuthStatus.FAILED, reason=str(exc))
                return self.info()
            self._qr_code = qr_code
            self._set(
                AdapterAuthStatus.WAITING_USER,
                AuthChallenge(qr_uri=qr_uri, instructions="使用手机微信扫码并确认登录"),
            )
            self._task = asyncio.create_task(
                self._poll(client, config), name=f"weixin-auth-{self._instance_id}"
            )
            return self.info()

    async def cancel(self, authenticated: bool) -> AdapterAuthInfo:
        async with self._lock:
            if self._task is not None:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
            self._qr_code = None
            if not authenticated:
                self.logged_out()
            return self.info()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    def _set(
        self,
        status: AdapterAuthStatus,
        challenge: AuthChallenge | None = None,
        reason: str | None = None,
    ) -> None:
        self._status = status
        self._challenge = challenge
        self._reason = reason

    async def _poll(self, client: WeixinClient, config: WeixinConfig) -> None:
        if self._qr_code is None:
            return
        try:
            while not self._stop.is_set():
                data = await client.request(
                    "GET",
                    "ilink/bot/get_qrcode_status",
                    params={"qrcode": self._qr_code},
                    timeout=config.long_poll_timeout,
                    headers={"iLink-App-ClientVersion": "1"},
                )
                status = string_value(data.get("status")) or "wait"
                if status == "confirmed":
                    token = string_value(data.get("bot_token"))
                    if not token:
                        raise WeixinAuthenticationError(
                            "Weixin login did not return a token"
                        )
                    await self._on_confirmed(
                        token,
                        string_value(data.get("ilink_bot_id")) or None,
                        string_value(data.get("baseurl")) or None,
                    )
                    self.authenticated()
                    return
                if status == "expired":
                    self._set(
                        AdapterAuthStatus.EXPIRED, reason="Weixin QR code expired"
                    )
                    return
                if status in {"cancel", "canceled", "denied"}:
                    self._set(
                        AdapterAuthStatus.FAILED, reason="Weixin login was cancelled"
                    )
                    return
                await asyncio.sleep(config.qr_poll_interval)
        except asyncio.CancelledError:
            raise
        except WeixinError as exc:
            self._set(AdapterAuthStatus.FAILED, reason=str(exc))
        finally:
            self._qr_code = None

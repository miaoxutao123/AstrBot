"""Weixin authentication, persistence, polling, and command tests."""

import asyncio
from collections.abc import Callable

from gateway.adapters.weixin import WeixinAdapter
from gateway.core import (
    AdapterAuthStatus,
    AdapterRegistry,
    AdapterRuntime,
    AdapterState,
    GatewayCommand,
    GatewayEvent,
    MemoryEventBus,
)
from gateway.profiles.im import (
    IM_MESSAGE_SEND,
    IM_TYPING_SET,
    IMOutboundMessage,
    IMSegment,
    IMTyping,
)
from gateway.state import MemoryStateStore
from tests.adapters.weixin.fakes import FakeWeixinClient


async def _eventually(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    async def check() -> None:
        while not predicate():  # noqa: ASYNC110 - bounded async test polling
            await asyncio.sleep(0)

    await asyncio.wait_for(check(), timeout)


def _runtime(
    fake: FakeWeixinClient, state: MemoryStateStore | None = None
) -> tuple[AdapterRuntime, MemoryEventBus]:
    registry = AdapterRegistry()
    registry.register(
        "weixin-main", WeixinAdapter("weixin-main", client_factory=lambda _config: fake)
    )
    bus = MemoryEventBus()
    return AdapterRuntime(registry, bus, state_store=state), bus


async def test_qr_login_receive_send_media_typing_and_token_expiry() -> None:
    fake = FakeWeixinClient()
    runtime, bus = _runtime(fake)
    events: list[GatewayEvent] = []

    async def collect(event: GatewayEvent) -> None:
        events.append(event)

    bus.subscribe(collect)
    await bus.start()
    info = await runtime.start("weixin-main")
    assert info.state == AdapterState.DEGRADED
    assert (
        await runtime.auth_info("weixin-main")
    ).status == AdapterAuthStatus.LOGGED_OUT

    auth = await runtime.start_auth("weixin-main")
    assert auth.status == AdapterAuthStatus.WAITING_USER
    assert auth.challenge is not None and auth.challenge.qr_uri == "weixin://login/qr"
    await fake.auth_results.put(
        {"status": "confirmed", "bot_token": "token", "ilink_bot_id": "bot"}
    )
    await _eventually(lambda: runtime.info("weixin-main").state == AdapterState.RUNNING)

    await fake.updates.put(
        {
            "ret": 0,
            "errcode": 0,
            "get_updates_buf": "cursor-1",
            "msgs": [
                {
                    "message_id": "m1",
                    "from_user_id": "user-1",
                    "context_token": "context-1",
                    "create_time": 100,
                    "item_list": [
                        {
                            "type": 1,
                            "text_item": {"text": "hello"},
                            "ref_msg": {
                                "message_item": {
                                    "message_id": "quoted-1",
                                    "type": 1,
                                    "text_item": {"text": "quoted"},
                                }
                            },
                        },
                        {
                            "type": 2,
                            "image_item": {
                                "media": {"encrypt_query_param": "image-query"}
                            },
                        },
                    ],
                }
            ],
        }
    )
    await _eventually(lambda: len(events) == 1)
    assert events[0].payload.data["segments"][0]["data"]["text"] == "hello"
    assert events[0].payload.data["segments"][1]["type"] == "image"
    assert events[0].payload.data["reply_to"] == "quoted-1"

    media = await runtime.media_store.put(b"outbound-image", "image/jpeg", "out.jpg")
    command = GatewayCommand(
        target=events[0].source,
        type=IM_MESSAGE_SEND,
        payload=IMOutboundMessage(
            (IMSegment.text("reply"), IMSegment.media("image", media))
        ).to_payload(),
    )
    assert (await runtime.execute(command)).status == "success"
    typing = GatewayCommand(
        target=events[0].source, type=IM_TYPING_SET, payload=IMTyping().to_payload()
    )
    assert (await runtime.execute(typing)).status == "success"
    assert fake.uploads[0][1] == b"outbound-image"

    await fake.updates.put({"ret": 0, "errcode": -14})
    await _eventually(
        lambda: runtime.info("weixin-main").state == AdapterState.DEGRADED
    )
    assert (
        await runtime.auth_info("weixin-main")
    ).status == AdapterAuthStatus.LOGGED_OUT
    await runtime.stop("weixin-main")
    await bus.stop()


async def test_session_is_restored_without_new_qr() -> None:
    state = MemoryStateStore()
    await state.set(
        "adapter/weixin-main/session",
        {
            "token": "persisted",
            "account_id": "bot",
            "base_url": "https://ilinkai.weixin.qq.com",
            "cursor": "saved",
            "context_tokens": {"user": "context"},
        },
    )
    fake = FakeWeixinClient()
    runtime, bus = _runtime(fake, state)
    await bus.start()
    info = await runtime.start("weixin-main")
    assert info.state == AdapterState.RUNNING
    assert (
        await runtime.auth_info("weixin-main")
    ).status == AdapterAuthStatus.AUTHENTICATED
    assert not any(
        endpoint.endswith("get_bot_qrcode") for _method, endpoint, _data in fake.calls
    )
    await runtime.stop("weixin-main")
    await bus.stop()


async def test_auth_cancel_and_expiry() -> None:
    fake = FakeWeixinClient()
    runtime, bus = _runtime(fake)
    await bus.start()
    await runtime.start("weixin-main")
    await runtime.start_auth("weixin-main")
    assert (
        await runtime.cancel_auth("weixin-main")
    ).status == AdapterAuthStatus.LOGGED_OUT
    await runtime.start_auth("weixin-main")
    await fake.auth_results.put({"status": "expired"})
    for _ in range(100):
        if (await runtime.auth_info("weixin-main")).status == AdapterAuthStatus.EXPIRED:
            break
        await asyncio.sleep(0)
    assert (await runtime.auth_info("weixin-main")).status == AdapterAuthStatus.EXPIRED
    await runtime.stop("weixin-main")
    await bus.stop()

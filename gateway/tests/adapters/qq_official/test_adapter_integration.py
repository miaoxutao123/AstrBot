"""QQ Official event, credential, resume, media, and command coverage."""

import asyncio
from collections.abc import Callable

import pytest

from gateway.adapters.qq_official import QQOfficialWebSocketAdapter
from gateway.core import (
    AdapterRegistry,
    AdapterRuntime,
    AdapterState,
    GatewayCommand,
    GatewayErrorCode,
    GatewayEvent,
    MemoryEventBus,
)
from gateway.profiles.im import (
    IM_MESSAGE_REPLY,
    IM_MESSAGE_SEND,
    IMMessage,
    IMOutboundMessage,
    IMSegment,
)
from gateway.secrets import MemorySecretStore
from gateway.state import MemoryStateStore
from tests.adapters.qq_official.fakes import FakeQQOfficialClient


async def eventually(predicate: Callable[[], bool]) -> None:
    async def wait() -> None:
        while not predicate():  # noqa: ASYNC110 - bounded test polling
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), 1)


def build(
    fake: FakeQQOfficialClient,
    state: MemoryStateStore | None = None,
    secrets: MemorySecretStore | None = None,
) -> tuple[AdapterRuntime, MemoryEventBus]:
    registry = AdapterRegistry()
    registry.register(
        "qq-main",
        QQOfficialWebSocketAdapter(
            "qq-main",
            {"app_id": {"env": "QQ_APP_ID"}, "secret": {"env": "QQ_SECRET"}},
            client_factory=lambda *_args: fake,
        ),
    )
    bus = MemoryEventBus()
    return AdapterRuntime(
        registry,
        bus,
        secret_provider=lambda key: {"QQ_APP_ID": "app", "QQ_SECRET": "secret"}.get(
            key
        ),
        state_store=state,
        secret_store=secrets,
    ), bus


@pytest.mark.parametrize(
    ("event_type", "data", "endpoint", "conversation"),
    [
        (
            "C2C_MESSAGE_CREATE",
            {"id": "c2c-1", "author": {"user_openid": "user"}, "content": "private"},
            "c2c:user",
            "private",
        ),
        (
            "GROUP_AT_MESSAGE_CREATE",
            {
                "id": "group-1",
                "group_openid": "group",
                "author": {"member_openid": "member"},
                "content": "group",
            },
            "group:group",
            "group",
        ),
        (
            "AT_MESSAGE_CREATE",
            {
                "id": "channel-1",
                "channel_id": "channel",
                "guild_id": "guild",
                "author": {"id": "member"},
                "content": "channel",
            },
            "channel:channel",
            "channel",
        ),
        (
            "DIRECT_MESSAGE_CREATE",
            {
                "id": "direct-1",
                "channel_id": "direct",
                "guild_id": "guild",
                "author": {"id": "member"},
                "content": "direct",
            },
            "direct:direct",
            "private",
        ),
    ],
)
async def test_message_domains(
    event_type: str, data: dict[str, object], endpoint: str, conversation: str
) -> None:
    fake = FakeQQOfficialClient()
    runtime, bus = build(fake)
    events: list[GatewayEvent] = []

    async def collect(event: GatewayEvent) -> None:
        events.append(event)

    bus.subscribe(collect)
    await bus.start()
    await runtime.start("qq-main")
    await fake.emit(event_type, data)
    await eventually(lambda: len(events) == 1)
    assert events[0].type == "im.message"
    assert events[0].source.endpoint_id == endpoint
    assert IMMessage.from_payload(events[0].payload).conversation.type == conversation
    await runtime.stop("qq-main")
    await bus.stop()


async def test_credentials_resume_unknown_media_send_rate_limit_and_shutdown() -> None:
    fake = FakeQQOfficialClient()
    state = MemoryStateStore()
    secrets = MemorySecretStore()
    runtime, bus = build(fake, state, secrets)
    events: list[GatewayEvent] = []

    async def collect(event: GatewayEvent) -> None:
        events.append(event)

    bus.subscribe(collect)
    await bus.start()
    assert (await runtime.start("qq-main")).state == AdapterState.RUNNING
    assert "dynamic-access-token" in str(
        await secrets.get("adapter/qq-main/access_token")
    )
    assert "dynamic-access-token" not in str(
        await state.get("adapter/qq-main/gateway_session")
    )
    assert await state.get("adapter/qq-main/gateway_session") == {
        "session_id": "session-1",
        "sequence": 10,
        "resume_url": "wss://resume.example.invalid",
    }
    await fake.emit("FUTURE_EVENT", {"future": "kept"})
    await fake.emit(
        "C2C_MESSAGE_CREATE",
        {
            "id": "message-1",
            "author": {"user_openid": "user"},
            "content": "hello",
            "message_reference": {"message_id": "quoted"},
            "attachments": [
                {
                    "url": "https://example.invalid/image.png",
                    "content_type": "image/png",
                }
            ],
            "msg_elements": [{"type": 999, "future": "kept"}],
        },
    )
    await eventually(lambda: len(events) == 2)
    assert events[0].payload.schema == "qq_official.event.v1"
    message_event = events[1]
    message = IMMessage.from_payload(message_event.payload)
    assert message.reply_to == "quoted"
    assert [segment.type for segment in message.segments] == ["text", "image", "raw"]
    outbound_media = await runtime.media_store.put(b"outbound", "image/png", "out.png")
    command = GatewayCommand(
        target=message_event.source,
        type=IM_MESSAGE_REPLY,
        payload=IMOutboundMessage(
            (IMSegment.text("reply"), IMSegment.media("image", outbound_media)),
            reply_to="message-1",
        ).to_payload(),
    )
    result = await runtime.execute(command)
    assert result.status == "success"
    assert [path for _method, path, _data in fake.calls] == [
        "/v2/users/user/files",
        "/v2/users/user/messages",
    ]
    fake.rate_limit = True
    limited = await runtime.execute(
        GatewayCommand(
            target=message_event.source,
            type=IM_MESSAGE_SEND,
            payload=IMOutboundMessage((IMSegment.text("limited"),)).to_payload(),
        )
    )
    assert (
        limited.error is not None
        and limited.error.code == GatewayErrorCode.RATE_LIMITED
    )
    assert limited.error.details["retry_after"] == 2.5
    fake.disconnect()
    assert runtime.info("qq-main").state == AdapterState.DEGRADED
    fake.resume()
    assert runtime.info("qq-main").state == AdapterState.RUNNING
    await fake.invalid_session()
    assert await state.get("adapter/qq-main/gateway_session") is None
    await runtime.stop("qq-main")
    await bus.stop()
    assert fake.stopped


async def test_missing_static_credentials_fail_startup() -> None:
    fake = FakeQQOfficialClient()
    registry = AdapterRegistry()
    registry.register(
        "qq-main",
        QQOfficialWebSocketAdapter(
            "qq-main",
            {"app_id": {"env": "APP"}, "secret": {"env": "SECRET"}},
            client_factory=lambda *_args: fake,
        ),
    )
    bus = MemoryEventBus()
    runtime = AdapterRuntime(registry, bus, secret_provider=lambda _key: None)
    await bus.start()
    info = await runtime.start("qq-main")
    assert info.state == AdapterState.FAILED
    assert not fake.calls
    await bus.stop()

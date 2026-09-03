"""Satori lifecycle, conversion, and command integration tests."""

import asyncio
from collections.abc import Callable

from gateway.adapters.satori import SatoriAdapter
from gateway.adapters.satori.protocol import EVENT, READY
from gateway.core import (
    AdapterRegistry,
    AdapterRuntime,
    AdapterState,
    GatewayCommand,
    GatewayErrorCode,
    GatewayEvent,
    MemoryEventBus,
    Payload,
)
from gateway.profiles.im import (
    IM_MESSAGE_REPLY,
    IM_MESSAGE_SEND,
    IMMessage,
    IMOutboundMessage,
    IMSegment,
)
from tests.adapters.satori.fakes import FakeSatoriClient


async def eventually(predicate: Callable[[], bool]) -> None:
    async def wait() -> None:
        while not predicate():  # noqa: ASYNC110 - bounded test polling
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout=1)


def runtime_with(fake: FakeSatoriClient) -> tuple[AdapterRuntime, MemoryEventBus]:
    registry = AdapterRegistry()
    registry.register(
        "satori-main",
        SatoriAdapter(
            "satori-main",
            {"token": {"env": "SATORI_TOKEN"}},
            client_factory=lambda _config, _token, _sequence: fake,
        ),
    )
    bus = MemoryEventBus()
    return AdapterRuntime(
        registry,
        bus,
        secret_provider=lambda key: "token" if key == "SATORI_TOKEN" else None,
    ), bus


async def test_multiple_login_event_conversion_media_reconnect_and_shutdown() -> None:
    fake = FakeSatoriClient()
    runtime, bus = runtime_with(fake)
    events: list[GatewayEvent] = []

    async def collect(event: GatewayEvent) -> None:
        events.append(event)

    bus.subscribe(collect)
    await bus.start()
    info = await runtime.start("satori-main")
    assert info.state == AdapterState.RUNNING
    assert fake.heartbeat_count == 1
    await fake.emit(
        {
            "op": READY,
            "body": {
                "sn": 9,
                "logins": [
                    {"platform": "discord", "user": {"id": "bot-a"}},
                    {"platform": "telegram", "user": {"id": "bot-b"}},
                ],
            },
        }
    )
    await fake.emit(
        {
            "op": EVENT,
            "body": {
                "sn": 10,
                "type": "message-created",
                "timestamp": 100,
                "login": {"platform": "telegram", "user": {"id": "bot-b"}},
                "user": {"id": "user-1", "name": "Alice"},
                "channel": {"id": "private-1"},
                "message": {
                    "id": "message-1",
                    "content": (
                        'hello<quote id="quoted"/><at id="user-2"/>'
                        '<img src="https://example.invalid/image.png"/>'
                        '<future value="kept"/>'
                    ),
                },
            },
        }
    )
    await eventually(lambda: len(events) == 1)
    assert len(events) == 1
    event = events[0]
    assert event.type == "im.message"
    assert event.source.adapter_type == "satori"
    assert event.source.endpoint_id == "account:telegram:bot-b/channel:private-1"
    assert event.metadata["satori_platform"] == "telegram"
    message = IMMessage.from_payload(event.payload)
    assert message.conversation.type == "private"
    assert message.reply_to == "quoted"
    assert [segment.type for segment in message.segments] == [
        "text",
        "reply",
        "mention",
        "image",
        "raw",
    ]
    assert await runtime.state_store.get("adapter/satori-main/sequence") == 10

    command = GatewayCommand(
        target=event.source,
        type=IM_MESSAGE_REPLY,
        payload=IMOutboundMessage(
            (IMSegment.text("reply"), IMSegment("mention", {"id": "user-1"})),
            reply_to="message-1",
        ).to_payload(),
    )
    result = await runtime.execute(command)
    assert result.status == "success" and result.external_id == "sent-1"
    method, path, data, login = fake.calls[0]
    assert (method, path) == ("POST", "/message.create")
    assert login.platform == "telegram" and login.self_id == "bot-b"
    assert data["channel_id"] == "private-1"
    assert '<quote id="message-1"/>' in str(data["content"])

    fake.disconnect()
    assert runtime.info("satori-main").state == AdapterState.DEGRADED
    fake.reconnect()
    assert runtime.info("satori-main").state == AdapterState.RUNNING
    fake.authentication_failure()
    assert runtime.info("satori-main").state == AdapterState.FAILED
    await runtime.stop("satori-main")
    await bus.stop()
    assert fake.stopped


async def test_channel_unknown_event_unsupported_command_and_auth_failure() -> None:
    fake = FakeSatoriClient()
    runtime, bus = runtime_with(fake)
    events: list[GatewayEvent] = []

    async def collect(event: GatewayEvent) -> None:
        events.append(event)

    bus.subscribe(collect)
    await bus.start()
    await runtime.start("satori-main")
    await fake.emit({"op": EVENT, "body": {"type": "future-event", "sn": 1}})
    await fake.emit(
        {
            "op": EVENT,
            "body": {
                "type": "message-created",
                "login": {"platform": "discord", "user": {"id": "bot"}},
                "user": {"id": "member", "name": "Member"},
                "channel": {"id": "channel"},
                "guild": {"id": "guild"},
                "message": {"id": "m2", "content": "channel"},
            },
        }
    )
    await eventually(lambda: len(events) == 1)
    assert IMMessage.from_payload(events[0].payload).conversation.type == "channel"
    unsupported = GatewayCommand(
        target=events[0].source,
        type="im.typing.set",
        payload=Payload("im.typing.v1", {"action": "typing"}),
    )
    unsupported_result = await runtime.execute(unsupported)
    assert unsupported_result.error is not None
    assert unsupported_result.error.code == GatewayErrorCode.CAPABILITY_NOT_SUPPORTED
    fake.fail_auth = True
    auth = GatewayCommand(
        target=events[0].source,
        type=IM_MESSAGE_SEND,
        payload=IMOutboundMessage((IMSegment.text("hello"),)).to_payload(),
    )
    auth_result = await runtime.execute(auth)
    assert auth_result.error is not None
    assert auth_result.error.code == GatewayErrorCode.AUTH_FAILED
    await runtime.stop("satori-main")
    await bus.stop()

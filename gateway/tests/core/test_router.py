"""Unit tests for payload-independent routing."""

from collections.abc import Awaitable, Callable

import pytest

from gateway.core import EndpointRef, GatewayEvent, Payload, RouteMatch, Router


@pytest.mark.asyncio
async def test_router_matches_transport_metadata_only() -> None:
    router = Router()
    routed: list[str] = []

    async def receive(event: GatewayEvent) -> None:
        routed.append(event.id)

    router.add_route("robot-events", RouteMatch(family="robot"), receive)
    robot_event = GatewayEvent(
        id="robot-event",
        source=EndpointRef("robot", "fake-robot", "robot-main", "/base"),
        type="robot.pose",
        payload=Payload("robot.pose.v1", {"x": 1}),
    )
    im_event = GatewayEvent(
        id="im-event",
        source=EndpointRef("im", "fake-im", "im-main", "user:1"),
        type="im.message",
        payload=Payload("im.message.v1", {"segments": []}),
    )

    await router.dispatch(robot_event)
    await router.dispatch(im_event)

    assert routed == ["robot-event"]


@pytest.mark.asyncio
async def test_router_matches_family_type_and_instance_independently() -> None:
    router = Router()
    routed: dict[str, list[str]] = {"family": [], "type": [], "instance": []}

    def destination(name: str) -> Callable[[GatewayEvent], Awaitable[None]]:
        async def receive(event: GatewayEvent) -> None:
            routed[name].append(event.source.adapter_id)

        return receive

    router.add_route("all-im", RouteMatch(family="im"), destination("family"))
    router.add_route(
        "all-telegram", RouteMatch(adapter_type="telegram"), destination("type")
    )
    router.add_route(
        "telegram-main",
        RouteMatch(adapter_id="telegram-main"),
        destination("instance"),
    )
    for adapter_type, adapter_id in (
        ("telegram", "telegram-main"),
        ("telegram", "telegram-backup"),
        ("onebot", "qq-main"),
    ):
        await router.dispatch(
            GatewayEvent(
                source=EndpointRef("im", adapter_type, adapter_id, "private:same"),
                type="im.message",
                payload=Payload("im.message.v1"),
            )
        )

    assert routed == {
        "family": ["telegram-main", "telegram-backup", "qq-main"],
        "type": ["telegram-main", "telegram-backup"],
        "instance": ["telegram-main"],
    }

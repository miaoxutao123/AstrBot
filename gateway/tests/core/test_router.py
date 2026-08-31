"""Unit tests for payload-independent routing."""

import pytest

from gateway.core import EndpointRef, GatewayEvent, Payload, RouteMatch, Router


@pytest.mark.asyncio
async def test_router_matches_transport_metadata_only() -> None:
    router = Router()
    routed: list[str] = []

    async def receive(event: GatewayEvent) -> None:
        routed.append(event.id)

    router.add_route("robot-events", RouteMatch(transport="robot"), receive)
    robot_event = GatewayEvent(
        id="robot-event",
        source=EndpointRef("robot", "robot-main", "/base"),
        type="robot.pose",
        payload=Payload("robot.pose.v1", {"x": 1}),
    )
    im_event = GatewayEvent(
        id="im-event",
        source=EndpointRef("im", "im-main", "user:1"),
        type="im.message",
        payload=Payload("im.message.v1", {"segments": []}),
    )

    await router.dispatch(robot_event)
    await router.dispatch(im_event)

    assert routed == ["robot-event"]

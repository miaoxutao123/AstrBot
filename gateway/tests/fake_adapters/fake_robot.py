"""Fake robot proving commands are not bound to chat semantics."""

from collections.abc import Mapping
from typing import Any

from gateway.core import (
    GATEWAY_API_VERSION,
    AdapterDescriptor,
    Capability,
    EndpointRef,
    GatewayEvent,
    Payload,
)

from .base import RecordingAdapter


class FakeRobotAdapter(RecordingAdapter):
    """Record motion commands and emit robot pose events."""

    DESCRIPTOR = AdapterDescriptor(
        id="fake-robot",
        name="Fake Robot",
        version="0.1.0",
        api_version=GATEWAY_API_VERSION,
        transport="robot",
        capabilities=(
            Capability("robot.move"),
            Capability("robot.stop"),
            Capability("robot.get_pose"),
        ),
    )

    def __init__(
        self,
        instance_id: str = "robot-main",
        config: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(instance_id, config)

    async def emit_pose(
        self,
        endpoint_id: str,
        x: float,
        y: float,
        heading: float,
    ) -> GatewayEvent:
        """Emit one robot pose observation.

        Args:
            endpoint_id: Robot endpoint identifier.
            x: X coordinate.
            y: Y coordinate.
            heading: Heading in radians.

        Returns:
            Event emitted through the Gateway context.
        """
        event = GatewayEvent(
            source=EndpointRef("robot", self.instance_id, endpoint_id),
            type="robot.pose",
            payload=Payload(
                schema="robot.pose.v1",
                data={"x": x, "y": y, "heading": heading},
            ),
        )
        await self.emit(event)
        return event

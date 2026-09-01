"""Fake sensor proving Core is not bound to IM semantics."""

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


class FakeSensorAdapter(RecordingAdapter):
    """Emit temperature telemetry through the generic event model."""

    DESCRIPTOR = AdapterDescriptor(
        adapter_type="fake-sensor",
        name="Fake Temperature Sensor",
        version="0.1.0",
        api_version=GATEWAY_API_VERSION,
        family="sensor",
        capabilities=(Capability("telemetry.temperature.read"),),
    )

    def __init__(
        self,
        instance_id: str = "sensor-main",
        config: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(instance_id, config)

    async def emit_temperature(
        self,
        endpoint_id: str,
        celsius: float,
    ) -> GatewayEvent:
        """Emit one temperature observation.

        Args:
            endpoint_id: Sensor endpoint identifier.
            celsius: Temperature in degrees Celsius.

        Returns:
            Event emitted through the Gateway context.
        """
        event = GatewayEvent(
            source=EndpointRef("sensor", "fake-sensor", self.instance_id, endpoint_id),
            type="telemetry.temperature",
            payload=Payload(
                schema="sensor.temperature.v1",
                data={"value": celsius, "unit": "celsius"},
            ),
        )
        await self.emit(event)
        return event

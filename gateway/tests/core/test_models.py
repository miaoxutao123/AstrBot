"""Unit tests for transport-neutral models."""

import pytest

from gateway.core import (
    Capability,
    CommandResult,
    EndpointRef,
    GatewayCommand,
    GatewayError,
    GatewayErrorCode,
    GatewayEvent,
    Payload,
)


def test_unknown_payload_schema_passes_through() -> None:
    payload = Payload("vendor.experimental.v7", {"opaque": [1, 2, 3]})
    endpoint = EndpointRef("iot", "custom", "custom-main", "device/1")
    event = GatewayEvent(source=endpoint, type="device.state", payload=payload)

    assert event.payload is payload
    assert endpoint.family == "iot"
    assert endpoint.adapter_type == "custom"
    assert event.payload.data == {"opaque": [1, 2, 3]}
    assert event.id.startswith("evt_")


@pytest.mark.parametrize("value", ["", "   "])
def test_endpoint_rejects_empty_identifiers(value: str) -> None:
    with pytest.raises(ValueError):
        EndpointRef("iot", "mqtt", "home", value)


def test_command_and_capability_are_transport_neutral() -> None:
    target = EndpointRef("robotics", "ros2", "robot-main", "/arm_controller")
    command = GatewayCommand(
        target=target,
        type="robot.move",
        payload=Payload("robot.motion.v1", {"linear_x": 0.3}),
    )
    capability = Capability("robot.move", schema={"type": "object"})

    assert command.id.startswith("cmd_")
    assert capability.name == command.type


def test_failed_result_requires_public_error() -> None:
    error = GatewayError(GatewayErrorCode.DELIVERY_FAILED, "delivery failed")
    result = CommandResult(command_id="cmd_1", status="failed", error=error)

    assert result.error == error
    with pytest.raises(ValueError):
        CommandResult(command_id="cmd_2", status="failed")

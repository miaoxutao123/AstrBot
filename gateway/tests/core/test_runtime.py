"""Unit and integration tests for adapter runtime isolation."""

from collections.abc import Mapping
from typing import Any

import pytest

from gateway.core import (
    AdapterContext,
    AdapterRegistry,
    AdapterRuntime,
    AdapterState,
    EndpointRef,
    GatewayCommand,
    GatewayLifecycle,
    MemoryEventBus,
    Payload,
)
from tests.fake_adapters import FakeRobotAdapter, FakeSensorAdapter


class FailingSensorAdapter(FakeSensorAdapter):
    """Fake adapter whose startup always fails."""

    def __init__(
        self,
        instance_id: str = "broken-sensor",
        config: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(instance_id, config)

    async def start(self, context: AdapterContext) -> None:
        """Fail during startup.

        Args:
            context: Unused adapter context.

        Raises:
            RuntimeError: Always raised to exercise isolation.
        """
        del context
        raise RuntimeError("sensor unavailable")


class FailingRobotAdapter(FakeRobotAdapter):
    """Fake adapter whose command execution always fails."""

    async def execute(self, command: GatewayCommand) -> Any:
        """Fail command execution.

        Args:
            command: Command used only to produce a deterministic failure.

        Raises:
            RuntimeError: Always raised to exercise command isolation.
        """
        raise RuntimeError(f"actuator failure for {command.id}")


@pytest.mark.asyncio
async def test_sensor_event_and_robot_command_share_core() -> None:
    bus = MemoryEventBus()
    registry = AdapterRegistry()
    sensor = FakeSensorAdapter()
    robot = FakeRobotAdapter()
    registry.register(sensor.instance_id, sensor)
    registry.register(robot.instance_id, robot)
    runtime = AdapterRuntime(registry, bus)
    lifecycle = GatewayLifecycle(bus, runtime)
    events: list[str] = []

    async def collect_event(event: Any) -> None:
        events.append(event.type)

    bus.subscribe(collect_event)
    states = await lifecycle.start()
    await sensor.emit_temperature("livingroom", 24.5)
    await bus.wait_until_idle()
    command = GatewayCommand(
        id="cmd_move",
        target=EndpointRef("robot", robot.instance_id, "/base"),
        type="robot.move",
        payload=Payload("robot.motion.v1", {"linear_x": 0.3}),
    )
    result = await runtime.execute(command)
    await lifecycle.stop()

    assert {info.state for info in states} == {AdapterState.RUNNING}
    assert events == ["telemetry.temperature"]
    assert result.status == "success"
    assert robot.commands == [command]


@pytest.mark.asyncio
async def test_start_failure_does_not_stop_other_adapters() -> None:
    bus = MemoryEventBus()
    registry = AdapterRegistry()
    registry.register("broken-sensor", FailingSensorAdapter())
    registry.register("robot-main", FakeRobotAdapter())
    runtime = AdapterRuntime(registry, bus)
    lifecycle = GatewayLifecycle(bus, runtime)

    states = await lifecycle.start()

    assert {info.adapter_id: info.state for info in states} == {
        "broken-sensor": AdapterState.FAILED,
        "robot-main": AdapterState.RUNNING,
    }
    await lifecycle.stop()


@pytest.mark.asyncio
async def test_runtime_rejects_offline_and_unknown_capability() -> None:
    bus = MemoryEventBus()
    registry = AdapterRegistry()
    robot = FakeRobotAdapter()
    registry.register(robot.instance_id, robot)
    runtime = AdapterRuntime(registry, bus)
    command = GatewayCommand(
        target=EndpointRef("robot", robot.instance_id, "/base"),
        type="robot.fly",
        payload=Payload("robot.motion.v1"),
    )

    offline_result = await runtime.execute(command)
    await bus.start()
    await runtime.start(robot.instance_id)
    unsupported_result = await runtime.execute(command)
    await runtime.stop(robot.instance_id)
    await bus.stop()

    assert offline_result.error is not None
    assert offline_result.error.code.value == "ADAPTER_OFFLINE"
    assert unsupported_result.error is not None
    assert unsupported_result.error.code.value == "CAPABILITY_NOT_SUPPORTED"


@pytest.mark.asyncio
async def test_adapter_execution_failure_is_contained() -> None:
    bus = MemoryEventBus()
    registry = AdapterRegistry()
    broken_robot = FailingRobotAdapter("broken-robot")
    healthy_robot = FakeRobotAdapter("healthy-robot")
    registry.register(broken_robot.instance_id, broken_robot)
    registry.register(healthy_robot.instance_id, healthy_robot)
    runtime = AdapterRuntime(registry, bus)
    lifecycle = GatewayLifecycle(bus, runtime)
    await lifecycle.start()
    broken_command = GatewayCommand(
        target=EndpointRef("robot", broken_robot.instance_id, "/base"),
        type="robot.stop",
        payload=Payload("robot.stop.v1"),
    )
    healthy_command = GatewayCommand(
        target=EndpointRef("robot", healthy_robot.instance_id, "/base"),
        type="robot.stop",
        payload=Payload("robot.stop.v1"),
    )

    broken_result = await runtime.execute(broken_command)
    healthy_result = await runtime.execute(healthy_command)
    await lifecycle.stop()

    assert broken_result.error is not None
    assert broken_result.error.code.value == "TRANSPORT_ERROR"
    assert healthy_result.status == "success"


@pytest.mark.asyncio
async def test_adapter_reports_degraded_and_recovers() -> None:
    bus = MemoryEventBus()
    registry = AdapterRegistry()
    robot = FakeRobotAdapter()
    registry.register(robot.instance_id, robot)
    runtime = AdapterRuntime(registry, bus)
    lifecycle = GatewayLifecycle(bus, runtime)
    await lifecycle.start()
    assert robot.context is not None

    robot.context.report_state(AdapterState.DEGRADED, "websocket disconnected")
    degraded = runtime.info(robot.instance_id)
    robot.context.report_state(AdapterState.RUNNING)
    recovered = runtime.info(robot.instance_id)
    await lifecycle.stop()

    assert degraded.state == AdapterState.DEGRADED
    assert degraded.reason == "websocket disconnected"
    assert recovered.state == AdapterState.RUNNING
    assert recovered.reason is None

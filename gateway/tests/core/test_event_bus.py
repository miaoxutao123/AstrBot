"""Unit tests for MemoryEventBus behavior."""

import asyncio

import pytest

from gateway.core import EndpointRef, GatewayEvent, MemoryEventBus, Payload


def make_event(index: int) -> GatewayEvent:
    """Build a deterministic test event.

    Args:
        index: Numeric event suffix.

    Returns:
        Test event.
    """
    return GatewayEvent(
        id=f"evt_{index}",
        source=EndpointRef("sensor", "sensor-main", "temperature/1"),
        type="telemetry.temperature",
        payload=Payload("sensor.temperature.v1", {"value": index}),
    )


@pytest.mark.asyncio
async def test_subscriber_failure_is_isolated() -> None:
    bus = MemoryEventBus(maxsize=2)
    received: list[str] = []

    async def failing_subscriber(event: GatewayEvent) -> None:
        raise RuntimeError(event.id)

    async def healthy_subscriber(event: GatewayEvent) -> None:
        received.append(event.id)

    bus.subscribe(failing_subscriber)
    bus.subscribe(healthy_subscriber)
    await bus.start()
    await bus.publish(make_event(1))
    await bus.wait_until_idle()
    await bus.stop()

    assert received == ["evt_1"]


@pytest.mark.asyncio
async def test_bounded_queue_applies_backpressure() -> None:
    bus = MemoryEventBus(maxsize=1)
    release = asyncio.Event()
    subscriber_started = asyncio.Event()

    async def slow_subscriber(_event: GatewayEvent) -> None:
        subscriber_started.set()
        await release.wait()

    bus.subscribe(slow_subscriber)
    await bus.start()
    await bus.publish(make_event(1))
    await subscriber_started.wait()
    await bus.publish(make_event(2))
    blocked_publish = asyncio.create_task(bus.publish(make_event(3)))
    await asyncio.sleep(0)

    assert not blocked_publish.done()
    release.set()
    await blocked_publish
    await bus.stop()


@pytest.mark.asyncio
async def test_stop_drains_queued_events() -> None:
    bus = MemoryEventBus(maxsize=4)
    received: list[str] = []

    async def subscriber(event: GatewayEvent) -> None:
        received.append(event.id)

    bus.subscribe(subscriber)
    await bus.start()
    await bus.publish(make_event(1))
    await bus.publish(make_event(2))
    await bus.stop()

    assert received == ["evt_1", "evt_2"]
    assert not bus.running

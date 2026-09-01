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
        source=EndpointRef("sensor", "fake-sensor", "sensor-main", "temperature/1"),
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


@pytest.mark.asyncio
async def test_publish_admitted_before_stop_is_drained() -> None:
    bus = MemoryEventBus(maxsize=1)
    release_first_event = asyncio.Event()
    first_event_started = asyncio.Event()
    received: list[str] = []

    async def slow_first_subscriber(event: GatewayEvent) -> None:
        received.append(event.id)
        if event.id == "evt_1":
            first_event_started.set()
            await release_first_event.wait()

    bus.subscribe(slow_first_subscriber)
    await bus.start()
    await bus.publish(make_event(1))
    await first_event_started.wait()
    await bus.publish(make_event(2))

    # This publish passes admission and blocks on the full queue while holding the
    # barrier. stop() must wait for it rather than placing _STOP ahead of the event.
    admitted_publish = asyncio.create_task(bus.publish(make_event(3)))
    await asyncio.sleep(0)
    assert not admitted_publish.done()
    concurrent_stop = asyncio.create_task(bus.stop())
    await asyncio.sleep(0)
    assert not concurrent_stop.done()

    release_first_event.set()
    await admitted_publish
    await concurrent_stop

    assert received == ["evt_1", "evt_2", "evt_3"]
    assert not bus.running

"""Unit tests for retained events and live subscription behavior."""

import pytest

from gateway.api.event_stream import EventFilter, EventStream, StreamClosed
from gateway.core import EndpointRef, GatewayEvent, Payload


def make_event(event_id: str, endpoint_id: str = "user:1") -> GatewayEvent:
    """Create a deterministic API event.

    Args:
        event_id: Stable event ID.
        endpoint_id: Source endpoint ID.

    Returns:
        Test Gateway event.
    """
    return GatewayEvent(
        id=event_id,
        source=EndpointRef("im", "im-main", endpoint_id),
        type="im.message",
        payload=Payload("im.message.v1", {"segments": []}),
    )


@pytest.mark.asyncio
async def test_event_stream_deduplicates_and_tracks_endpoint() -> None:
    stream = EventStream()
    subscription = stream.subscribe(EventFilter())
    event = make_event("evt_1")

    await stream.ingest(event)
    await stream.ingest(event)

    assert await subscription.queue.get() is event
    assert subscription.queue.empty()
    assert stream.get("evt_1") is event
    assert stream.endpoints()[0].last_event_id == "evt_1"


@pytest.mark.asyncio
async def test_slow_client_is_closed_explicitly() -> None:
    stream = EventStream(client_queue_size=1)
    subscription = stream.subscribe(EventFilter())

    await stream.ingest(make_event("evt_1"))
    await stream.ingest(make_event("evt_2"))

    item = await subscription.queue.get()
    assert isinstance(item, StreamClosed)
    assert item.reason == "live event queue overflow"
    assert stream.subscription_count == 0


@pytest.mark.asyncio
async def test_reconnect_replays_events_after_cursor() -> None:
    stream = EventStream()
    await stream.ingest(make_event("evt_1"))
    await stream.ingest(make_event("evt_2"))
    await stream.ingest(make_event("evt_3", endpoint_id="user:2"))

    subscription = stream.subscribe(
        EventFilter(adapter_id="im-main"),
        last_event_id="evt_1",
    )

    replayed = [
        await subscription.queue.get(),
        await subscription.queue.get(),
    ]
    assert all(isinstance(item, GatewayEvent) for item in replayed)
    assert [item.id for item in replayed if isinstance(item, GatewayEvent)] == [
        "evt_2",
        "evt_3",
    ]
    assert subscription.cursor_found


@pytest.mark.asyncio
async def test_event_stream_applies_all_subscription_filters() -> None:
    stream = EventStream()
    subscription = stream.subscribe(
        EventFilter(
            transport="im",
            adapter_id="im-main",
            event_type="im.message",
        )
    )

    await stream.ingest(
        GatewayEvent(
            id="evt_sensor",
            source=EndpointRef("sensor", "sensor-main", "temperature:1"),
            type="telemetry.temperature",
            payload=Payload("sensor.temperature.v1", {"value": 20.0}),
        )
    )
    assert subscription.queue.empty()

    matching = make_event("evt_im")
    await stream.ingest(matching)
    assert await subscription.queue.get() is matching

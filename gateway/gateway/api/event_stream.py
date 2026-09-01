"""Bounded in-memory event history and live subscriptions."""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass

from gateway.core import EndpointRef, GatewayEvent


@dataclass(frozen=True, slots=True)
class EventFilter:
    """Filter live events using transport metadata only.

    Args:
        family: Optional transport family.
        adapter_type: Optional adapter implementation type.
        adapter_id: Optional configured adapter ID.
        event_type: Optional event type.
    """

    family: str | None = None
    adapter_type: str | None = None
    adapter_id: str | None = None
    event_type: str | None = None

    def matches(self, event: GatewayEvent) -> bool:
        """Return whether an event matches this filter.

        Args:
            event: Event being considered.

        Returns:
            ``True`` if every configured field matches.
        """
        return (
            self.family in {None, "*", event.source.family}
            and self.adapter_type in {None, "*", event.source.adapter_type}
            and self.adapter_id in {None, "*", event.source.adapter_id}
            and self.event_type in {None, "*", event.type}
        )


@dataclass(frozen=True, slots=True)
class EndpointRecord:
    """Track an endpoint observed from transport events.

    Args:
        endpoint: Observed endpoint.
        last_event_id: Most recent event from the endpoint.
        last_seen: Timestamp of the most recent event.
    """

    endpoint: EndpointRef
    last_event_id: str
    last_seen: float


@dataclass(frozen=True, slots=True)
class StreamClosed:
    """Signal an explicit live subscription termination.

    Args:
        reason: Safe reason sent to the WebSocket client.
    """

    reason: str


StreamItem = GatewayEvent | StreamClosed


@dataclass(slots=True)
class EventSubscription:
    """Represent one live event subscription.

    Args:
        token: Store-owned subscription identifier.
        queue: Bounded live delivery queue.
        cursor_found: Whether a requested reconnect cursor was in memory.
        replay_truncated: Whether replay exceeded the client queue capacity.
    """

    token: int
    queue: asyncio.Queue[StreamItem]
    cursor_found: bool = True
    replay_truncated: bool = False


class EventStream:
    """Store recent events, observed endpoints, and live subscribers.

    Args:
        history_size: Maximum in-memory events available by ID or replay.
        client_queue_size: Maximum pending events per WebSocket client.

    Raises:
        ValueError: If either bound is not positive.
    """

    def __init__(
        self,
        history_size: int = 1024,
        client_queue_size: int = 256,
    ) -> None:
        if history_size <= 0 or client_queue_size <= 0:
            raise ValueError("event stream bounds must be positive")
        self._history_size = history_size
        self._client_queue_size = client_queue_size
        self._events: OrderedDict[str, GatewayEvent] = OrderedDict()
        self._endpoints: dict[EndpointRef, EndpointRecord] = {}
        self._subscriptions: dict[
            int,
            tuple[EventFilter, asyncio.Queue[StreamItem]],
        ] = {}
        self._next_token = 1

    @property
    def subscription_count(self) -> int:
        """Return the number of active live subscriptions.

        Returns:
            Active subscription count.
        """
        return len(self._subscriptions)

    async def ingest(self, event: GatewayEvent) -> None:
        """Record and fan out one event, deduplicating by event ID.

        Args:
            event: Event received from MemoryEventBus.
        """
        if event.id in self._events:
            return
        self._events[event.id] = event
        while len(self._events) > self._history_size:
            self._events.popitem(last=False)
        self._endpoints[event.source] = EndpointRecord(
            endpoint=event.source,
            last_event_id=event.id,
            last_seen=event.timestamp,
        )
        overflowed: list[int] = []
        for token, (event_filter, queue) in self._subscriptions.items():
            if not event_filter.matches(event):
                continue
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                overflowed.append(token)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(StreamClosed("live event queue overflow"))
        for token in overflowed:
            self._subscriptions.pop(token, None)

    def get(self, event_id: str) -> GatewayEvent | None:
        """Return a recent event by ID.

        Args:
            event_id: Stable event identifier.

        Returns:
            Event when retained in memory, otherwise ``None``.
        """
        return self._events.get(event_id)

    def endpoints(self) -> list[EndpointRecord]:
        """Return observed endpoints in deterministic order.

        Returns:
            Endpoint records sorted by transport and identifiers.
        """
        return sorted(
            self._endpoints.values(),
            key=lambda record: (
                record.endpoint.family,
                record.endpoint.adapter_type,
                record.endpoint.adapter_id,
                record.endpoint.endpoint_id,
            ),
        )

    def subscribe(
        self,
        event_filter: EventFilter,
        last_event_id: str | None = None,
    ) -> EventSubscription:
        """Create a bounded live subscription with optional in-memory replay.

        Args:
            event_filter: Transport-level event filter.
            last_event_id: Event after which retained matching events are replayed.

        Returns:
            Live subscription and replay status.
        """
        token = self._next_token
        self._next_token += 1
        queue: asyncio.Queue[StreamItem] = asyncio.Queue(
            maxsize=self._client_queue_size
        )
        cursor_found = True
        replay_truncated = False
        replay: list[GatewayEvent] = []
        if last_event_id is not None:
            event_ids = list(self._events)
            if last_event_id in self._events:
                start_index = event_ids.index(last_event_id) + 1
                replay = [
                    self._events[event_id]
                    for event_id in event_ids[start_index:]
                    if event_filter.matches(self._events[event_id])
                ]
            else:
                cursor_found = False
        if len(replay) > self._client_queue_size:
            replay = replay[-self._client_queue_size :]
            replay_truncated = True
        for event in replay:
            queue.put_nowait(event)
        self._subscriptions[token] = (event_filter, queue)
        return EventSubscription(
            token=token,
            queue=queue,
            cursor_found=cursor_found,
            replay_truncated=replay_truncated,
        )

    def unsubscribe(self, token: int) -> None:
        """Remove a live subscription if present.

        Args:
            token: Subscription identifier.
        """
        self._subscriptions.pop(token, None)

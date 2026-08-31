"""Bounded in-memory event bus with graceful shutdown."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import cast

from .errors import GatewayError, GatewayErrorCode, GatewayException
from .models import GatewayEvent

EventSubscriber = Callable[[GatewayEvent], Awaitable[None]]
_STOP = object()


class MemoryEventBus:
    """Dispatch events from a bounded ``asyncio.Queue`` to subscribers.

    Args:
        maxsize: Maximum number of events waiting for dispatch.
        logger: Optional logger used for lifecycle and isolated failures.

    Raises:
        ValueError: If ``maxsize`` is not positive.
    """

    def __init__(
        self,
        maxsize: int = 1024,
        logger: logging.Logger | None = None,
    ) -> None:
        if maxsize <= 0:
            raise ValueError("event bus maxsize must be positive")
        self._queue: asyncio.Queue[GatewayEvent | object] = asyncio.Queue(
            maxsize=maxsize
        )
        self._logger = logger or logging.getLogger("gateway.event_bus")
        self._subscribers: dict[int, EventSubscriber] = {}
        self._next_subscriber_id = 1
        self._task: asyncio.Task[None] | None = None
        self._accepting = False
        self._admission_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        """Return whether the bus accepts new events.

        Returns:
            ``True`` between ``start`` and ``stop``.
        """
        return self._accepting

    def subscribe(self, subscriber: EventSubscriber) -> int:
        """Register an asynchronous event subscriber.

        Args:
            subscriber: Callback invoked for every event.

        Returns:
            Subscription token used to unsubscribe.
        """
        token = self._next_subscriber_id
        self._next_subscriber_id += 1
        self._subscribers[token] = subscriber
        return token

    def unsubscribe(self, token: int) -> None:
        """Remove a subscription if it exists.

        Args:
            token: Token returned by ``subscribe``.
        """
        self._subscribers.pop(token, None)

    async def start(self) -> None:
        """Start the dispatcher task. Calling this twice is harmless."""
        async with self._lifecycle_lock:
            if self._task is not None and not self._task.done():
                return
            async with self._admission_lock:
                self._accepting = True
                self._task = asyncio.create_task(
                    self._dispatch(),
                    name="gateway_memory_event_bus",
                )

    async def publish(self, event: GatewayEvent) -> None:
        """Publish an event, waiting when the bounded queue is full.

        Args:
            event: Event to dispatch.

        Raises:
            GatewayException: If the bus is not running or is shutting down.
        """
        # Hold admission through queue insertion. If the queue is full, stop waits
        # until this already-admitted event is queued before beginning its drain.
        async with self._admission_lock:
            if not self._accepting:
                raise GatewayException(
                    GatewayError(
                        GatewayErrorCode.TRANSPORT_ERROR,
                        "event bus is not accepting events",
                        retryable=True,
                    )
                )
            self._logger.debug(
                "event_received",
                extra={
                    "event_id": event.id,
                    "correlation_id": event.correlation_id,
                    "adapter_id": event.source.adapter_id,
                    "endpoint_id": event.source.endpoint_id,
                },
            )
            await self._queue.put(event)

    async def wait_until_idle(self) -> None:
        """Wait until every queued event has completed dispatch."""
        await self._queue.join()

    async def stop(self) -> None:
        """Stop accepting events and drain queued work before returning."""
        async with self._lifecycle_lock:
            task = self._task
            if task is None:
                async with self._admission_lock:
                    self._accepting = False
                return
            async with self._admission_lock:
                self._accepting = False
            await self._queue.join()
            await self._queue.put(_STOP)
            await task
            self._task = None

    async def _dispatch(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is _STOP:
                    return
                event = cast(GatewayEvent, item)
                results = await asyncio.gather(
                    *(subscriber(event) for subscriber in self._subscribers.values()),
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, BaseException):
                        self._logger.error(
                            "event_subscriber_failed",
                            exc_info=(
                                type(result),
                                result,
                                result.__traceback__,
                            ),
                            extra={
                                "event_id": event.id,
                                "correlation_id": event.correlation_id,
                                "adapter_id": event.source.adapter_id,
                                "endpoint_id": event.source.endpoint_id,
                            },
                        )
                self._logger.debug(
                    "event_dispatched",
                    extra={
                        "event_id": event.id,
                        "correlation_id": event.correlation_id,
                        "adapter_id": event.source.adapter_id,
                        "endpoint_id": event.source.endpoint_id,
                    },
                )
            finally:
                self._queue.task_done()

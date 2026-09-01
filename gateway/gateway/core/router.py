"""Deterministic transport-level event routing."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .models import GatewayEvent

RouteDestination = Callable[[GatewayEvent], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RouteMatch:
    """Match immutable transport attributes without inspecting payload content.

    Args:
        family: Transport family or ``*``.
        adapter_type: Adapter implementation type or ``*``.
        adapter_id: Configured adapter identifier or ``*``.
        event_type: Event type or ``*``.
    """

    family: str = "*"
    adapter_type: str = "*"
    adapter_id: str = "*"
    event_type: str = "*"

    def matches(self, event: GatewayEvent) -> bool:
        """Return whether an event matches this rule.

        Args:
            event: Event being routed.

        Returns:
            ``True`` when every non-wildcard field matches.
        """
        return (
            self.family in {"*", event.source.family}
            and self.adapter_type in {"*", event.source.adapter_type}
            and self.adapter_id in {"*", event.source.adapter_id}
            and self.event_type in {"*", event.type}
        )


class Router:
    """Route events to named destinations using transport metadata only."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._routes: dict[str, tuple[RouteMatch, RouteDestination]] = {}
        self._logger = logger or logging.getLogger("gateway.router")

    def add_route(
        self,
        name: str,
        match: RouteMatch,
        destination: RouteDestination,
    ) -> None:
        """Add a named route.

        Args:
            name: Unique route identifier.
            match: Transport-level match rule.
            destination: Async destination callback.

        Raises:
            ValueError: If the name is empty or already exists.
        """
        if not name or not name.strip():
            raise ValueError("route name must not be empty")
        if name in self._routes:
            raise ValueError(f"route already exists: {name}")
        self._routes[name] = (match, destination)

    def remove_route(self, name: str) -> None:
        """Remove a route if it exists.

        Args:
            name: Route identifier.
        """
        self._routes.pop(name, None)

    async def dispatch(self, event: GatewayEvent) -> None:
        """Deliver an event to every matching route with failure isolation.

        Args:
            event: Event received from the event bus.
        """
        destinations = [
            (name, destination)
            for name, (match, destination) in self._routes.items()
            if match.matches(event)
        ]
        results = await asyncio.gather(
            *(destination(event) for _, destination in destinations),
            return_exceptions=True,
        )
        for (name, _), result in zip(destinations, results, strict=True):
            if isinstance(result, BaseException):
                self._logger.error(
                    "route_destination_failed",
                    exc_info=(type(result), result, result.__traceback__),
                    extra={"route": name, "event_id": event.id},
                )

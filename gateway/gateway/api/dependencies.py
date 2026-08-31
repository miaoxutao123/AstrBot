"""Shared FastAPI dependencies and application services."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from fastapi import Request

from gateway.core import AdapterRuntime, GatewayLifecycle, MemoryEventBus
from gateway.media import MediaStore

from .auth import ApiKeyStore, ApiPrincipal
from .event_stream import EventStream


@dataclass(slots=True)
class ApiServices:
    """Hold API services without introducing module globals.

    Args:
        runtime: Adapter runtime used by routes.
        event_bus: Shared Core event bus.
        lifecycle: Ordered Core lifecycle.
        api_keys: API key authenticator.
        events: In-memory event and endpoint catalog.
        media: Opaque media store shared with adapter contexts.
        heartbeat_interval: WebSocket heartbeat interval in seconds.
    """

    runtime: AdapterRuntime
    event_bus: MemoryEventBus
    lifecycle: GatewayLifecycle
    api_keys: ApiKeyStore
    events: EventStream
    media: MediaStore
    heartbeat_interval: float


def get_services(request: Request) -> ApiServices:
    """Return Gateway API services from application state.

    Args:
        request: Current FastAPI request.

    Returns:
        Application-scoped API services.
    """
    return cast(ApiServices, request.app.state.gateway_services)


def require_scope(scope: str) -> Callable[[Request], ApiPrincipal]:
    """Build a FastAPI dependency requiring one API scope.

    Args:
        scope: Scope required by a route.

    Returns:
        Request dependency returning an authorized principal.
    """

    def authorize(request: Request) -> ApiPrincipal:
        services = get_services(request)
        principal = services.api_keys.authenticate(request.headers)
        services.api_keys.require(principal, scope)
        return principal

    return authorize

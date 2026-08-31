"""Dependency-free Gateway Core public API."""

from .adapter import (
    GATEWAY_API_VERSION,
    AdapterContext,
    AdapterDescriptor,
    TransportAdapter,
)
from .errors import GatewayError, GatewayErrorCode, GatewayException
from .event_bus import MemoryEventBus
from .lifecycle import GatewayLifecycle
from .models import (
    Capability,
    CommandResult,
    EndpointRef,
    GatewayCommand,
    GatewayEvent,
    Payload,
)
from .registry import AdapterRegistry
from .router import RouteMatch, Router
from .runtime import AdapterRuntime, AdapterRuntimeInfo, AdapterState

__all__ = [
    "GATEWAY_API_VERSION",
    "AdapterContext",
    "AdapterDescriptor",
    "AdapterRegistry",
    "AdapterRuntime",
    "AdapterRuntimeInfo",
    "AdapterState",
    "Capability",
    "CommandResult",
    "EndpointRef",
    "GatewayCommand",
    "GatewayError",
    "GatewayErrorCode",
    "GatewayEvent",
    "GatewayException",
    "GatewayLifecycle",
    "MemoryEventBus",
    "Payload",
    "RouteMatch",
    "Router",
    "TransportAdapter",
]

"""Dependency-free Gateway Core public API."""

from .adapter import (
    GATEWAY_API_VERSION,
    AdapterContext,
    AdapterDescriptor,
    TransportAdapter,
)
from .auth import AdapterAuthInfo, AdapterAuthStatus, AuthChallenge
from .errors import GatewayError, GatewayErrorCode, GatewayException
from .event_bus import MemoryEventBus
from .health import AdapterState
from .lifecycle import GatewayLifecycle
from .models import (
    Capability,
    CommandResult,
    EndpointRef,
    GatewayCommand,
    GatewayEvent,
    Payload,
)
from .registry import AdapterDiscoveryResult, AdapterRegistry
from .router import RouteMatch, Router
from .runtime import AdapterRuntime, AdapterRuntimeInfo

__all__ = [
    "GATEWAY_API_VERSION",
    "AdapterContext",
    "AdapterAuthInfo",
    "AdapterAuthStatus",
    "AdapterDescriptor",
    "AdapterDiscoveryResult",
    "AdapterRegistry",
    "AdapterRuntime",
    "AdapterRuntimeInfo",
    "AdapterState",
    "AuthChallenge",
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

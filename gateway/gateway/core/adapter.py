"""Minimal extension contract for transport adapters."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .health import AdapterState
from .models import (
    Capability,
    CommandResult,
    EndpointRef,
    GatewayCommand,
    GatewayEvent,
)

GATEWAY_API_VERSION = 1
EventEmitter = Callable[[GatewayEvent], Awaitable[None]]
SecretProvider = Callable[[str], str | None]
StateReporter = Callable[[AdapterState, str | None], None]


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    """Describe an adapter implementation and its static capabilities.

    Args:
        id: Adapter type identifier used by configuration and entry points.
        name: Human-readable adapter name.
        version: Adapter implementation version.
        api_version: Gateway Adapter API version implemented by the adapter.
        transport: Transport family implemented by the adapter.
        capabilities: Capabilities common to every endpoint of this adapter.

    Raises:
        ValueError: If a required field is empty or the API version is invalid.
    """

    id: str
    name: str
    version: str
    api_version: int
    transport: str
    capabilities: tuple[Capability, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Validate descriptor fields.

        Raises:
            ValueError: If a required field is empty or the API version is invalid.
        """
        for field_name, value in (
            ("id", self.id),
            ("name", self.name),
            ("version", self.version),
            ("transport", self.transport),
        ):
            if not value or not value.strip():
                raise ValueError(f"adapter descriptor {field_name} must not be empty")
        if self.api_version < 1:
            raise ValueError("adapter API version must be positive")


class AdapterContext:
    """Expose only event emission, logging, and secrets to an adapter.

    Args:
        adapter_id: Configured adapter instance identifier.
        emit: Runtime callback used to publish events.
        logger: Logger scoped to the adapter instance.
        get_secret: Secret resolver controlled by the Gateway host.
        report_state: Runtime callback for connection health transitions.
    """

    def __init__(
        self,
        adapter_id: str,
        emit: EventEmitter,
        logger: logging.Logger,
        get_secret: SecretProvider,
        report_state: StateReporter,
    ) -> None:
        self.adapter_id = adapter_id
        self._emit = emit
        self._logger = logger
        self._get_secret = get_secret
        self._report_state = report_state

    async def emit(self, event: GatewayEvent) -> None:
        """Publish an event produced by this adapter instance.

        Args:
            event: Transport-neutral event to publish.

        Raises:
            ValueError: If the event claims a different adapter instance.
        """
        if event.source.adapter_id != self.adapter_id:
            raise ValueError(
                "adapter context cannot emit an event for a different adapter_id"
            )
        await self._emit(event)

    def logger(self) -> logging.Logger:
        """Return the adapter-scoped logger.

        Returns:
            Logger supplied by the Gateway host.
        """
        return self._logger

    def get_secret(self, key: str) -> str | None:
        """Resolve a secret without exposing the host configuration object.

        Args:
            key: Host-defined secret key or reference.

        Returns:
            Secret value when present, otherwise ``None``.

        Raises:
            ValueError: If the secret key is empty.
        """
        if not key or not key.strip():
            raise ValueError("secret key must not be empty")
        return self._get_secret(key)

    def report_state(
        self,
        state: AdapterState,
        reason: str | None = None,
    ) -> None:
        """Report connection health after adapter startup.

        Adapters use this for runtime transitions such as disconnect, reconnect,
        or terminal authentication failure. Lifecycle-owned transitional states
        cannot be reported by an adapter.

        Args:
            state: New health state: running, degraded, or failed.
            reason: Required diagnostic reason for degraded and failed states.

        Raises:
            ValueError: If the state is lifecycle-owned or lacks a required reason.
        """
        if state not in {
            AdapterState.RUNNING,
            AdapterState.DEGRADED,
            AdapterState.FAILED,
        }:
            raise ValueError(f"adapter cannot report lifecycle state: {state.value}")
        if state in {AdapterState.DEGRADED, AdapterState.FAILED} and (
            reason is None or not reason.strip()
        ):
            raise ValueError(f"{state.value} state requires a reason")
        self._report_state(state, reason)


class TransportAdapter(ABC):
    """Primary and intentionally narrow Gateway extension interface."""

    @property
    @abstractmethod
    def descriptor(self) -> AdapterDescriptor:
        """Return immutable adapter metadata.

        Returns:
            Adapter descriptor implemented by this instance.
        """
        raise NotImplementedError

    @abstractmethod
    async def start(self, context: AdapterContext) -> None:
        """Initialize transport resources and return when ready.

        This method must create any long-running receive/reconnect tasks and then
        return. It must not await a run-forever loop. After return, Runtime marks
        the adapter running unless it reported degraded or failed during startup.

        Args:
            context: Minimal host services available to the adapter.
        """
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        """Cancel background tasks and return after resources are released."""
        raise NotImplementedError

    @abstractmethod
    async def execute(self, command: GatewayCommand) -> CommandResult:
        """Execute a command against this adapter.

        Args:
            command: Command already addressed to this adapter instance.

        Returns:
            Stable execution result.
        """
        raise NotImplementedError

    @abstractmethod
    async def capabilities(
        self,
        endpoint: EndpointRef | None = None,
    ) -> list[Capability]:
        """Return adapter-wide or endpoint-specific capabilities.

        Args:
            endpoint: Optional endpoint to inspect.

        Returns:
            Capabilities supported at the requested scope.
        """
        raise NotImplementedError

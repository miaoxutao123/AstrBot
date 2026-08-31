"""Isolated lifecycle and command execution for adapter instances."""

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from gateway.media import MediaStore, MemoryMediaStore
from gateway.state import (
    AdapterStateStore,
    MemoryStateStore,
    NamespacedStateStore,
)

from .adapter import AdapterContext
from .auth import AdapterAuthInfo
from .errors import GatewayError, GatewayErrorCode, GatewayException
from .event_bus import MemoryEventBus
from .health import AdapterState
from .models import (
    Capability,
    CommandResult,
    EndpointRef,
    GatewayCommand,
)
from .registry import AdapterRegistry


@dataclass(frozen=True, slots=True)
class AdapterRuntimeInfo:
    """Expose adapter state without leaking the adapter object.

    Args:
        adapter_id: Configured adapter instance identifier.
        adapter_type: Adapter descriptor type identifier.
        state: Current lifecycle state.
        reason: Adapter-reported health reason, if any.
        error: Last safe lifecycle error, if any.
    """

    adapter_id: str
    adapter_type: str
    state: AdapterState
    reason: str | None = None
    error: GatewayError | None = None


class AdapterRuntime:
    """Manage adapter isolation, state, and command dispatch.

    Args:
        registry: Configured adapter instance registry.
        event_bus: Event destination shared by adapter contexts.
        logger: Optional runtime logger.
        secret_provider: Host-controlled secret resolver. Environment lookup is
            used by default.
        state_store: Host-owned adapter persistence backend.
        media_store: Host-owned opaque media backend.
    """

    def __init__(
        self,
        registry: AdapterRegistry,
        event_bus: MemoryEventBus,
        logger: logging.Logger | None = None,
        secret_provider: Callable[[str], str | None] | None = None,
        state_store: AdapterStateStore | None = None,
        media_store: MediaStore | None = None,
    ) -> None:
        self._registry = registry
        self._event_bus = event_bus
        self._logger = logger or logging.getLogger("gateway.runtime")
        self._secret_provider = secret_provider or os.getenv
        self._state_store = state_store or MemoryStateStore()
        self._media_store = media_store or MemoryMediaStore()
        self._states: dict[str, AdapterState] = {}
        self._reasons: dict[str, str | None] = {}
        self._errors: dict[str, GatewayError | None] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def media_store(self) -> MediaStore:
        """Return the media store shared with adapter contexts.

        Returns:
            Host-owned media store.
        """
        return self._media_store

    @property
    def state_store(self) -> AdapterStateStore:
        """Return the underlying host adapter state store.

        Returns:
            Host-owned state store. Adapters receive only namespaced views.
        """
        return self._state_store

    def info(self, adapter_id: str) -> AdapterRuntimeInfo:
        """Return current state for a configured adapter.

        Args:
            adapter_id: Configured adapter identifier.

        Returns:
            Immutable runtime information.

        Raises:
            GatewayException: If the adapter is not registered.
        """
        adapter = self._registry.get(adapter_id)
        return AdapterRuntimeInfo(
            adapter_id=adapter_id,
            adapter_type=adapter.descriptor.id,
            state=self._states.get(adapter_id, AdapterState.STOPPED),
            reason=self._reasons.get(adapter_id),
            error=self._errors.get(adapter_id),
        )

    def list_info(self) -> list[AdapterRuntimeInfo]:
        """Return current state for every configured adapter.

        Returns:
            Runtime information sorted by adapter identifier.
        """
        return [self.info(adapter_id) for adapter_id, _ in self._registry.instances()]

    async def start(self, adapter_id: str) -> AdapterRuntimeInfo:
        """Start one adapter while containing its failure.

        Args:
            adapter_id: Configured adapter identifier.

        Returns:
            Resulting runtime state. Startup exceptions become ``FAILED`` state.

        Raises:
            GatewayException: If the adapter is not registered.
        """
        adapter = self._registry.get(adapter_id)
        lock = self._locks.setdefault(adapter_id, asyncio.Lock())
        async with lock:
            if self._states.get(adapter_id) in {
                AdapterState.RUNNING,
                AdapterState.DEGRADED,
            }:
                return self.info(adapter_id)
            self._states[adapter_id] = AdapterState.STARTING
            self._reasons[adapter_id] = None
            self._errors[adapter_id] = None
            context = AdapterContext(
                adapter_id=adapter_id,
                emit=self._event_bus.publish,
                logger=logging.getLogger(f"gateway.adapter.{adapter_id}"),
                get_secret=self._secret_provider,
                report_state=lambda state, reason: self._report_state(
                    adapter_id,
                    state,
                    reason,
                ),
                state=NamespacedStateStore(self._state_store, adapter_id),
                media=self._media_store,
            )
            try:
                await adapter.start(context)
            except asyncio.CancelledError:
                self._states[adapter_id] = AdapterState.STOPPED
                self._reasons[adapter_id] = None
                raise
            except Exception as exc:
                error = GatewayError(
                    GatewayErrorCode.TRANSPORT_ERROR,
                    f"adapter failed to start: {adapter_id}",
                    retryable=True,
                )
                self._states[adapter_id] = AdapterState.FAILED
                self._reasons[adapter_id] = error.message
                self._errors[adapter_id] = error
                self._logger.error(
                    "adapter_failed",
                    exc_info=exc,
                    extra={"adapter_id": adapter_id},
                )
            else:
                if self._states.get(adapter_id) == AdapterState.STARTING:
                    self._states[adapter_id] = AdapterState.RUNNING
                if self._states.get(adapter_id) == AdapterState.RUNNING:
                    self._logger.info(
                        "adapter_started",
                        extra={"adapter_id": adapter_id},
                    )
            return self.info(adapter_id)

    async def start_all(self) -> list[AdapterRuntimeInfo]:
        """Start all adapters concurrently with per-adapter isolation.

        Returns:
            Resulting state of every configured adapter.
        """
        return await asyncio.gather(
            *(self.start(adapter_id) for adapter_id, _ in self._registry.instances())
        )

    async def stop(self, adapter_id: str) -> AdapterRuntimeInfo:
        """Stop one adapter and release its resources.

        Args:
            adapter_id: Configured adapter identifier.

        Returns:
            Resulting runtime state. Shutdown exceptions become ``FAILED`` state.

        Raises:
            GatewayException: If the adapter is not registered.
        """
        adapter = self._registry.get(adapter_id)
        lock = self._locks.setdefault(adapter_id, asyncio.Lock())
        async with lock:
            current_state = self._states.get(adapter_id, AdapterState.STOPPED)
            if current_state == AdapterState.STOPPED:
                return self.info(adapter_id)
            self._states[adapter_id] = AdapterState.STOPPING
            self._reasons[adapter_id] = None
            try:
                await adapter.stop()
            except asyncio.CancelledError:
                self._states[adapter_id] = AdapterState.FAILED
                self._reasons[adapter_id] = "adapter shutdown was cancelled"
                raise
            except Exception as exc:
                error = GatewayError(
                    GatewayErrorCode.TRANSPORT_ERROR,
                    f"adapter failed to stop: {adapter_id}",
                )
                self._states[adapter_id] = AdapterState.FAILED
                self._reasons[adapter_id] = error.message
                self._errors[adapter_id] = error
                self._logger.error(
                    "adapter_failed",
                    exc_info=exc,
                    extra={"adapter_id": adapter_id},
                )
            else:
                self._states[adapter_id] = AdapterState.STOPPED
                self._reasons[adapter_id] = None
                self._errors[adapter_id] = None
            return self.info(adapter_id)

    async def stop_all(self) -> list[AdapterRuntimeInfo]:
        """Stop all configured adapters concurrently.

        Returns:
            Resulting state of every configured adapter.
        """
        return await asyncio.gather(
            *(self.stop(adapter_id) for adapter_id, _ in self._registry.instances())
        )

    async def restart(self, adapter_id: str) -> AdapterRuntimeInfo:
        """Restart one adapter.

        Args:
            adapter_id: Configured adapter identifier.

        Returns:
            Resulting runtime state.
        """
        await self.stop(adapter_id)
        return await self.start(adapter_id)

    def _report_state(
        self,
        adapter_id: str,
        state: AdapterState,
        reason: str | None,
    ) -> None:
        current_state = self._states.get(adapter_id, AdapterState.STOPPED)
        if current_state in {AdapterState.STOPPED, AdapterState.STOPPING}:
            self._logger.warning(
                "adapter_state_report_ignored",
                extra={
                    "adapter_id": adapter_id,
                    "reported_state": state.value,
                },
            )
            return
        self._states[adapter_id] = state
        self._reasons[adapter_id] = reason
        if state == AdapterState.FAILED:
            self._errors[adapter_id] = GatewayError(
                GatewayErrorCode.TRANSPORT_ERROR,
                reason or f"adapter failed: {adapter_id}",
                retryable=True,
            )
            log_event = "adapter_failed"
        elif state == AdapterState.DEGRADED:
            self._errors[adapter_id] = None
            log_event = "adapter_degraded"
        else:
            self._errors[adapter_id] = None
            log_event = "adapter_recovered"
        self._logger.info(
            log_event,
            extra={
                "adapter_id": adapter_id,
                "adapter_state": state.value,
                "reason": reason,
            },
        )

    async def capabilities(
        self,
        adapter_id: str,
        endpoint: EndpointRef | None = None,
    ) -> list[Capability]:
        """Query adapter-wide or endpoint-specific capabilities.

        Args:
            adapter_id: Configured adapter identifier.
            endpoint: Optional endpoint to inspect.

        Returns:
            Capabilities declared by the adapter.

        Raises:
            GatewayException: If the adapter is not registered or the endpoint
                addresses another adapter instance.
        """
        adapter = self._registry.get(adapter_id)
        if endpoint is not None and endpoint.adapter_id != adapter_id:
            raise GatewayException(
                GatewayError(
                    GatewayErrorCode.ENDPOINT_NOT_FOUND,
                    "endpoint belongs to a different adapter",
                )
            )
        return await adapter.capabilities(endpoint)

    async def auth_info(self, adapter_id: str) -> AdapterAuthInfo:
        """Return one adapter's generic interactive authentication state."""
        return await self._registry.get(adapter_id).auth_info()

    async def start_auth(self, adapter_id: str) -> AdapterAuthInfo:
        """Start one adapter's generic interactive authentication flow."""
        return await self._registry.get(adapter_id).start_auth()

    async def cancel_auth(self, adapter_id: str) -> AdapterAuthInfo:
        """Cancel one adapter's generic interactive authentication flow."""
        return await self._registry.get(adapter_id).cancel_auth()

    async def execute(self, command: GatewayCommand) -> CommandResult:
        """Validate and dispatch a command to its target adapter.

        Args:
            command: Transport-neutral command.

        Returns:
            Adapter result or a stable failed result. Adapter exceptions never
            escape this boundary.
        """
        adapter_id = command.target.adapter_id
        self._logger.debug(
            "command_received",
            extra={
                "command_id": command.id,
                "correlation_id": command.correlation_id,
                "adapter_id": adapter_id,
                "endpoint_id": command.target.endpoint_id,
            },
        )
        try:
            adapter = self._registry.get(adapter_id)
        except GatewayException as exc:
            return CommandResult(
                command_id=command.id,
                status="failed",
                error=exc.error,
            )
        if self._states.get(adapter_id, AdapterState.STOPPED) not in {
            AdapterState.RUNNING,
            AdapterState.DEGRADED,
        }:
            return CommandResult(
                command_id=command.id,
                status="failed",
                error=GatewayError(
                    GatewayErrorCode.ADAPTER_OFFLINE,
                    f"adapter is not running: {adapter_id}",
                    retryable=True,
                ),
            )
        try:
            capabilities = await adapter.capabilities(command.target)
            if command.type not in {capability.name for capability in capabilities}:
                return CommandResult(
                    command_id=command.id,
                    status="failed",
                    error=GatewayError(
                        GatewayErrorCode.CAPABILITY_NOT_SUPPORTED,
                        f"capability is not supported: {command.type}",
                    ),
                )
            result = await adapter.execute(command)
            if result.command_id != command.id:
                raise ValueError("adapter returned a result for a different command")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.error(
                "command_failed",
                exc_info=exc,
                extra={
                    "command_id": command.id,
                    "correlation_id": command.correlation_id,
                    "adapter_id": adapter_id,
                    "endpoint_id": command.target.endpoint_id,
                },
            )
            return CommandResult(
                command_id=command.id,
                status="failed",
                error=GatewayError(
                    GatewayErrorCode.TRANSPORT_ERROR,
                    "adapter command execution failed",
                    retryable=True,
                ),
            )
        self._logger.info(
            "command_executed",
            extra={
                "command_id": command.id,
                "correlation_id": command.correlation_id,
                "adapter_id": adapter_id,
                "endpoint_id": command.target.endpoint_id,
            },
        )
        return result

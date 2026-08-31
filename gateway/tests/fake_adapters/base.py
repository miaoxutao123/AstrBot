"""Reusable recording behavior for fake transport adapters."""

from collections.abc import Mapping
from typing import Any, ClassVar

from gateway.core import (
    AdapterContext,
    AdapterDescriptor,
    Capability,
    CommandResult,
    EndpointRef,
    GatewayCommand,
    GatewayEvent,
    TransportAdapter,
)


class RecordingAdapter(TransportAdapter):
    """Record lifecycle and commands for deterministic contract tests.

    Args:
        instance_id: Configured adapter instance identifier.
        config: Adapter-owned configuration.
    """

    DESCRIPTOR: ClassVar[AdapterDescriptor]

    def __init__(
        self,
        instance_id: str,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self.instance_id = instance_id
        self.config = dict(config or {})
        self.context: AdapterContext | None = None
        self.started = False
        self.commands: list[GatewayCommand] = []

    @property
    def descriptor(self) -> AdapterDescriptor:
        """Return the fake adapter descriptor.

        Returns:
            Descriptor declared by the concrete fake adapter.
        """
        return self.DESCRIPTOR

    async def start(self, context: AdapterContext) -> None:
        """Store the context and mark the fake adapter running.

        Args:
            context: Minimal Gateway host context.
        """
        self.context = context
        self.started = True

    async def stop(self) -> None:
        """Mark the fake adapter stopped."""
        self.started = False
        self.context = None

    async def execute(self, command: GatewayCommand) -> CommandResult:
        """Record a command and return a deterministic external identifier.

        Args:
            command: Command dispatched by the runtime.

        Returns:
            Successful command result.

        Raises:
            RuntimeError: If the adapter is not running.
        """
        if not self.started:
            raise RuntimeError("fake adapter is offline")
        self.commands.append(command)
        return CommandResult(
            command_id=command.id,
            status="success",
            external_id=f"fake:{len(self.commands)}",
        )

    async def capabilities(
        self,
        endpoint: EndpointRef | None = None,
    ) -> list[Capability]:
        """Return static capabilities when the endpoint belongs to this adapter.

        Args:
            endpoint: Optional endpoint to validate.

        Returns:
            Static capabilities or an empty list for a foreign endpoint.
        """
        if endpoint is not None and (
            endpoint.adapter_id != self.instance_id
            or endpoint.transport != self.descriptor.transport
        ):
            return []
        return list(self.descriptor.capabilities)

    async def emit(self, event: GatewayEvent) -> None:
        """Emit a prepared event through the stored adapter context.

        Args:
            event: Fake event to publish.

        Raises:
            RuntimeError: If the adapter is not running.
        """
        if self.context is None:
            raise RuntimeError("fake adapter is offline")
        await self.context.emit(event)

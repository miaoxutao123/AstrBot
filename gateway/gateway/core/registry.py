"""Adapter factory discovery and configured instance registry."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any, cast

from .adapter import GATEWAY_API_VERSION, TransportAdapter
from .errors import GatewayError, GatewayErrorCode, GatewayException

AdapterFactory = Callable[[str, Mapping[str, Any]], TransportAdapter]


@dataclass(frozen=True, slots=True)
class AdapterDiscoveryResult:
    """Summarize isolated entry-point discovery outcomes.

    Args:
        loaded: Adapter types successfully registered.
        failed: Adapter types that failed to load or register.
        errors: Safe error messages keyed by failed adapter type.
    """

    loaded: tuple[str, ...] = field(default_factory=tuple)
    failed: tuple[str, ...] = field(default_factory=tuple)
    errors: dict[str, str] = field(default_factory=dict)


class AdapterRegistry:
    """Register adapter factories and configured instances without plugin hooks."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._factories: dict[str, AdapterFactory] = {}
        self._instances: dict[str, TransportAdapter] = {}
        self._logger = logger or logging.getLogger("gateway.registry")

    def register_factory(self, adapter_type: str, factory: AdapterFactory) -> None:
        """Register one adapter factory.

        Args:
            adapter_type: Entry-point and descriptor type identifier.
            factory: Callable accepting instance ID and configuration.

        Raises:
            ValueError: If the type is empty or already registered.
        """
        if not adapter_type or not adapter_type.strip():
            raise ValueError("adapter type must not be empty")
        if adapter_type in self._factories:
            raise ValueError(f"adapter factory already registered: {adapter_type}")
        self._factories[adapter_type] = factory

    def discover(
        self,
        group: str = "astrbot_gateway.adapters",
    ) -> AdapterDiscoveryResult:
        """Discover adapter factories through standard Python entry points.

        Entry points may expose a class or another callable with the signature
        ``(instance_id, config) -> TransportAdapter``. Discovery never imports a
        concrete transport from Core itself.

        Args:
            group: Entry-point group to scan.

        Returns:
            Per-adapter loaded and failed outcomes. One broken entry point never
            prevents later entry points from loading.
        """
        entry_points = metadata.entry_points()
        selected = entry_points.select(group=group)
        loaded: list[str] = []
        failed: list[str] = []
        errors: dict[str, str] = {}
        for entry_point in selected:
            try:
                factory = entry_point.load()
                if not callable(factory):
                    raise TypeError(
                        f"adapter entry point {entry_point.name} must be callable"
                    )
                self.register_factory(
                    entry_point.name,
                    cast(AdapterFactory, factory),
                )
            except Exception as exc:
                failed.append(entry_point.name)
                errors[entry_point.name] = str(exc) or type(exc).__name__
                self._logger.error(
                    "adapter_discovery_failed",
                    exc_info=exc,
                    extra={"adapter_type": entry_point.name},
                )
                continue
            loaded.append(entry_point.name)
        return AdapterDiscoveryResult(
            loaded=tuple(loaded),
            failed=tuple(failed),
            errors=errors,
        )

    def create(
        self,
        instance_id: str,
        adapter_type: str,
        config: Mapping[str, Any] | None = None,
    ) -> TransportAdapter:
        """Instantiate and register a configured adapter.

        Args:
            instance_id: Unique configured adapter identifier.
            adapter_type: Registered adapter factory identifier.
            config: Adapter-owned configuration mapping.

        Returns:
            Newly registered adapter instance.

        Raises:
            GatewayException: If the factory does not exist or the adapter is
                incompatible with this Gateway API.
            TypeError: If the factory returns a non-adapter object.
            ValueError: If the instance identifier is already registered.
        """
        factory = self._factories.get(adapter_type)
        if factory is None:
            raise GatewayException(
                GatewayError(
                    GatewayErrorCode.ADAPTER_NOT_FOUND,
                    f"adapter type is not registered: {adapter_type}",
                )
            )
        adapter = factory(instance_id, config or {})
        if not isinstance(adapter, TransportAdapter):
            raise TypeError(f"factory {adapter_type} did not return TransportAdapter")
        if adapter.descriptor.id != adapter_type:
            raise ValueError(
                f"factory type {adapter_type} does not match descriptor "
                f"{adapter.descriptor.id}"
            )
        self.register(instance_id, adapter)
        return adapter

    def register(self, instance_id: str, adapter: TransportAdapter) -> None:
        """Register a configured adapter instance.

        Args:
            instance_id: Unique configured adapter identifier.
            adapter: Adapter implementation instance.

        Raises:
            ValueError: If the identifier is empty or already registered.
            GatewayException: If the adapter API version is incompatible.
        """
        if not instance_id or not instance_id.strip():
            raise ValueError("adapter instance id must not be empty")
        if instance_id in self._instances:
            raise ValueError(f"adapter instance already registered: {instance_id}")
        if adapter.descriptor.api_version != GATEWAY_API_VERSION:
            raise GatewayException(
                GatewayError(
                    GatewayErrorCode.INVALID_COMMAND,
                    "adapter API version is incompatible",
                    details={
                        "adapter_id": instance_id,
                        "adapter_api": adapter.descriptor.api_version,
                        "gateway_api": GATEWAY_API_VERSION,
                    },
                )
            )
        self._instances[instance_id] = adapter

    def unregister(self, instance_id: str) -> TransportAdapter:
        """Remove and return an adapter instance.

        Args:
            instance_id: Configured adapter identifier.

        Returns:
            Removed adapter instance.

        Raises:
            GatewayException: If the instance does not exist.
        """
        adapter = self._instances.pop(instance_id, None)
        if adapter is None:
            raise GatewayException(
                GatewayError(
                    GatewayErrorCode.ADAPTER_NOT_FOUND,
                    f"adapter instance not found: {instance_id}",
                )
            )
        return adapter

    def get(self, instance_id: str) -> TransportAdapter:
        """Return an adapter instance.

        Args:
            instance_id: Configured adapter identifier.

        Returns:
            Registered adapter instance.

        Raises:
            GatewayException: If the instance does not exist.
        """
        adapter = self._instances.get(instance_id)
        if adapter is None:
            raise GatewayException(
                GatewayError(
                    GatewayErrorCode.ADAPTER_NOT_FOUND,
                    f"adapter instance not found: {instance_id}",
                )
            )
        return adapter

    def instances(self) -> list[tuple[str, TransportAdapter]]:
        """Return registered instances in deterministic order.

        Returns:
            Pairs of instance identifier and adapter.
        """
        return sorted(self._instances.items())

    def factory_types(self) -> list[str]:
        """Return registered factory type names.

        Returns:
            Sorted adapter type names.
        """
        return sorted(self._factories)

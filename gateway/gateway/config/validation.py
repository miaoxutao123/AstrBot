"""Offline configuration and adapter compatibility validation."""

from dataclasses import dataclass

from gateway.core import AdapterRegistry

from .schema import GatewayConfig
from .secrets import EnvironmentSecretResolver


@dataclass(frozen=True, slots=True)
class ConfigCheckResult:
    """Summarize an offline host configuration check.

    Args:
        adapter_types: Successfully discovered adapter types.
        configured_instances: Enabled, compatible adapter instance IDs.
        discovery_failures: Safe entry-point failure messages.
    """

    adapter_types: tuple[str, ...]
    configured_instances: tuple[str, ...]
    discovery_failures: dict[str, str]


def check_config(
    config: GatewayConfig,
    resolver: EnvironmentSecretResolver | None = None,
) -> ConfigCheckResult:
    """Validate secrets, discovery, factories, and Adapter API compatibility.

    This function never starts an adapter or opens a network connection.

    Args:
        config: Validated Gateway configuration.
        resolver: Optional environment resolver.

    Returns:
        Offline validation summary.

    Raises:
        ValueError: If a secret, factory, adapter config, or API version is invalid.
    """
    secret_resolver = resolver or EnvironmentSecretResolver()
    for reference in config.secret_references():
        secret_resolver.require(reference)
    registry = AdapterRegistry()
    discovery = registry.discover()
    configured: list[str] = []
    for adapter in config.adapters:
        if not adapter.enabled:
            continue
        if adapter.type in discovery.failed:
            raise ValueError(
                f"configured adapter type failed discovery: {adapter.type}"
            )
        registry.create(adapter.id, adapter.type, adapter.config)
        configured.append(adapter.id)
    return ConfigCheckResult(
        adapter_types=tuple(registry.factory_types()),
        configured_instances=tuple(configured),
        discovery_failures=discovery.errors,
    )

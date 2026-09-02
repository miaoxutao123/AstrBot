"""Composition root for the standalone AstrBot-Gateway process."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gateway.api import ApiKey, create_app
from gateway.config import (
    EnvironmentSecretResolver,
    GatewayConfig,
    SecretReference,
    check_config,
)
from gateway.control_plane import AgentRegistry, ManagedAdapterStore
from gateway.core import AdapterRegistry, AdapterRuntime, MemoryEventBus
from gateway.media import FileMediaStore, MediaStore, MemoryMediaStore
from gateway.secrets import AdapterSecretStore, MemorySecretStore
from gateway.secrets.encrypted_file import EncryptedFileSecretStore
from gateway.state import AdapterStateStore, MemoryStateStore, SQLiteStateStore


@dataclass(frozen=True, slots=True)
class GatewayHost:
    """Expose the composed process services.

    Args:
        app: FastAPI ASGI application.
        registry: Configured adapter registry.
        runtime: Configured adapter runtime.
        event_bus: Shared Core event bus.
        state_store: Host-owned adapter state backend.
        media_store: Host-owned media backend.
    """

    app: Any
    registry: AdapterRegistry
    runtime: AdapterRuntime
    event_bus: MemoryEventBus
    state_store: AdapterStateStore
    secret_store: AdapterSecretStore
    media_store: MediaStore
    agent_registry: AgentRegistry
    managed_adapter_store: ManagedAdapterStore


def build_host(
    config: GatewayConfig,
    resolver: EnvironmentSecretResolver | None = None,
) -> GatewayHost:
    """Build a runnable Gateway host without starting network resources.

    Args:
        config: Validated runtime configuration.
        resolver: Optional environment secret resolver.

    Returns:
        Fully composed Gateway host.

    Raises:
        ValueError: If secrets, adapters, or optional API dependencies are invalid.
    """
    secret_resolver = resolver or EnvironmentSecretResolver()
    check_config(config, secret_resolver)
    base_directory = config.source.parent
    if config.state.type == "sqlite":
        state_path = Path(config.state.path)
        if not state_path.is_absolute():
            state_path = base_directory / state_path
        state_store: AdapterStateStore = SQLiteStateStore(state_path)
    else:
        state_store = MemoryStateStore()
    if config.media.type == "file":
        media_path = Path(config.media.path)
        if not media_path.is_absolute():
            media_path = base_directory / media_path
        media_store: MediaStore = FileMediaStore(
            media_path,
            config.media.max_upload_size,
            config.media.ttl_seconds,
        )
    else:
        media_store = MemoryMediaStore(
            config.media.max_upload_size,
            config.media.ttl_seconds,
        )
    if config.secrets.type == "encrypted_file":
        secrets_path = Path(config.secrets.path)
        if not secrets_path.is_absolute():
            secrets_path = base_directory / secrets_path
        secret_store: AdapterSecretStore = EncryptedFileSecretStore(
            secrets_path,
            secret_resolver.require(SecretReference("ASTRBOT_GATEWAY_MASTER_KEY")),
        )
    else:
        secret_store = MemorySecretStore()
    registry = AdapterRegistry()
    discovery = registry.discover()
    for adapter in config.adapters:
        if adapter.enabled:
            if adapter.type in discovery.failed:
                raise ValueError(
                    f"configured adapter type failed discovery: {adapter.type}"
                )
            registry.create(adapter.id, adapter.type, adapter.config)
    event_bus = MemoryEventBus()
    runtime = AdapterRuntime(
        registry,
        event_bus,
        secret_provider=secret_resolver.get,
        state_store=state_store,
        secret_store=secret_store,
        media_store=media_store,
    )
    api_keys = [
        ApiKey(
            key.id,
            secret_resolver.require(key.secret),
            key.scopes,
        )
        for key in config.api.keys
    ]
    agent_registry = AgentRegistry(base_directory / "data" / "gateway-agents.db")
    managed_adapter_store = ManagedAdapterStore(
        base_directory / "data" / "gateway-managed-adapters.db"
    )
    app = create_app(
        runtime,
        event_bus,
        api_keys,
        heartbeat_interval=config.api.heartbeat_interval,
        event_history_size=config.api.event_history_size,
        client_queue_size=config.api.client_queue_size,
        agent_registry=agent_registry,
        managed_adapter_store=managed_adapter_store,
    )
    return GatewayHost(
        app,
        registry,
        runtime,
        event_bus,
        state_store,
        secret_store,
        media_store,
        agent_registry,
        managed_adapter_store,
    )

"""Small data-only runtime configuration schema."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SecretReference:
    """Reference a secret stored in an environment variable.

    Args:
        env: Environment variable name.

    Raises:
        ValueError: If the environment variable name is empty.
    """

    env: str

    def __post_init__(self) -> None:
        """Validate the environment variable name.

        Raises:
            ValueError: If the name is empty.
        """
        if not self.env or not self.env.strip():
            raise ValueError("secret environment variable must not be empty")


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """Configure the Gateway HTTP server.

    Args:
        host: Bind host.
        port: Bind TCP port.
    """

    host: str = "127.0.0.1"
    port: int = 6186


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    """Configure one adapter instance.

    Args:
        id: Unique configured instance identifier.
        type: Installed adapter entry-point name.
        enabled: Whether the host should instantiate the adapter.
        config: Adapter-owned configuration mapping.
    """

    id: str
    type: str
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ApiKeyConfig:
    """Configure one API caller.

    Args:
        id: Non-secret caller identifier.
        secret: Environment secret reference.
        scopes: Granted authorization scopes.
    """

    id: str
    secret: SecretReference
    scopes: frozenset[str]


@dataclass(frozen=True, slots=True)
class ApiConfig:
    """Configure API authentication and WebSocket bounds.

    Args:
        keys: API key definitions.
        heartbeat_interval: WebSocket heartbeat seconds.
        event_history_size: Retained in-memory event count.
        client_queue_size: Pending events per WebSocket client.
    """

    keys: tuple[ApiKeyConfig, ...]
    heartbeat_interval: float = 20.0
    event_history_size: int = 1024
    client_queue_size: int = 256


@dataclass(frozen=True, slots=True)
class StateConfig:
    """Configure adapter state persistence.

    Args:
        type: `memory` or `sqlite`.
        path: SQLite path relative to the configuration file.
    """

    type: str = "memory"
    path: str = "data/gateway-state.db"


@dataclass(frozen=True, slots=True)
class DynamicSecretsConfig:
    """Configure dynamic adapter credential persistence.

    The encryption master key is intentionally absent and is always resolved from
    the fixed ``ASTRBOT_GATEWAY_MASTER_KEY`` environment variable.
    """

    type: str = "memory"
    path: str = "data/gateway-secrets.json"


@dataclass(frozen=True, slots=True)
class MediaConfig:
    """Configure opaque media storage.

    Args:
        type: `memory` or `file`.
        path: File-store directory relative to the configuration file.
        max_upload_size: Maximum object bytes.
        ttl_seconds: Default object lifetime.
    """

    type: str = "memory"
    path: str = "data/media"
    max_upload_size: int = 20 * 1024 * 1024
    ttl_seconds: float = 3600.0


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    """Complete validated Gateway host configuration.

    Args:
        source: Absolute configuration file path.
        server: HTTP server configuration.
        adapters: Configured adapter instances.
        api: API authentication and delivery settings.
        state: Adapter persistence configuration.
        secrets: Dynamic credential persistence configuration.
        media: Media storage configuration.
    """

    source: Path
    server: ServerConfig
    adapters: tuple[AdapterConfig, ...]
    api: ApiConfig
    state: StateConfig
    secrets: DynamicSecretsConfig
    media: MediaConfig

    def secret_references(self) -> tuple[SecretReference, ...]:
        """Return every explicit secret reference.

        Returns:
            API and adapter secret references in deterministic order.
        """
        references = [key.secret for key in self.api.keys]
        if self.secrets.type == "encrypted_file":
            references.append(SecretReference("ASTRBOT_GATEWAY_MASTER_KEY"))
        for adapter in self.adapters:
            if not adapter.enabled:
                continue
            stack: list[object] = [adapter.config]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    if set(value) == {"env"} and isinstance(value["env"], str):
                        references.append(SecretReference(value["env"]))
                    else:
                        stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
        return tuple(references)

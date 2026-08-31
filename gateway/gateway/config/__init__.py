"""Gateway runtime configuration API."""

from .loader import ConfigError, load_config
from .schema import (
    AdapterConfig,
    ApiConfig,
    ApiKeyConfig,
    GatewayConfig,
    MediaConfig,
    SecretReference,
    ServerConfig,
    StateConfig,
)
from .secrets import EnvironmentSecretResolver
from .validation import ConfigCheckResult, check_config

__all__ = [
    "AdapterConfig",
    "ApiConfig",
    "ApiKeyConfig",
    "ConfigError",
    "ConfigCheckResult",
    "EnvironmentSecretResolver",
    "GatewayConfig",
    "MediaConfig",
    "SecretReference",
    "ServerConfig",
    "StateConfig",
    "load_config",
    "check_config",
]

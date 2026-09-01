"""Strict YAML loader for the standalone Gateway host."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .schema import (
    AdapterConfig,
    ApiConfig,
    ApiKeyConfig,
    DynamicSecretsConfig,
    GatewayConfig,
    MediaConfig,
    SecretReference,
    ServerConfig,
    StateConfig,
)


class ConfigError(ValueError):
    """Represent a safe configuration validation failure."""


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ConfigError(f"{field_name} must be an object")
    return value


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field_name} must be a non-empty string")
    return value


def _integer(value: object, field_name: str, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ConfigError(f"{field_name} must be an integer >= {minimum}")
    return value


def _number(value: object, field_name: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{field_name} must be a positive number")
    return float(value)


def _secret(value: object, field_name: str) -> SecretReference:
    mapping = _mapping(value, field_name)
    if set(mapping) != {"env"}:
        raise ConfigError(f"{field_name} must contain only an env reference")
    return SecretReference(_string(mapping.get("env"), f"{field_name}.env"))


def load_config(path: Path) -> GatewayConfig:
    """Load and validate one Gateway YAML file.

    Args:
        path: Configuration file path.

    Returns:
        Validated immutable configuration.

    Raises:
        ConfigError: If YAML parsing or schema validation fails.
    """
    source = path.resolve()
    try:
        loaded = yaml.safe_load(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file was not found: {source}") from exc
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError("configuration file could not be parsed") from exc
    root = _mapping(loaded, "configuration")
    unknown_root = set(root) - {
        "server",
        "adapters",
        "api",
        "state",
        "secrets",
        "media",
    }
    if unknown_root:
        raise ConfigError(
            f"unknown configuration fields: {', '.join(sorted(unknown_root))}"
        )

    server_data = _mapping(root.get("server"), "server")
    host = server_data.get("host", "127.0.0.1")
    port = server_data.get("port", 6186)
    server = ServerConfig(
        host=_string(host, "server.host"),
        port=_integer(port, "server.port"),
    )
    if server.port > 65535:
        raise ConfigError("server.port must be <= 65535")

    raw_adapters = root.get("adapters", [])
    if not isinstance(raw_adapters, Sequence) or isinstance(raw_adapters, str):
        raise ConfigError("adapters must be an array")
    adapters: list[AdapterConfig] = []
    adapter_ids: set[str] = set()
    for index, raw_adapter in enumerate(raw_adapters):
        item = _mapping(raw_adapter, f"adapters[{index}]")
        adapter_id = _string(item.get("id"), f"adapters[{index}].id")
        if adapter_id in adapter_ids:
            raise ConfigError(f"duplicate adapter id: {adapter_id}")
        adapter_ids.add(adapter_id)
        adapter_type = _string(item.get("type"), f"adapters[{index}].type")
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"adapters[{index}].enabled must be a boolean")
        adapter_config = dict(_mapping(item.get("config"), f"adapters[{index}].config"))
        adapters.append(
            AdapterConfig(adapter_id, adapter_type, enabled, adapter_config)
        )

    api_data = _mapping(root.get("api"), "api")
    raw_keys = api_data.get("keys", [])
    if not isinstance(raw_keys, Sequence) or isinstance(raw_keys, str):
        raise ConfigError("api.keys must be an array")
    api_keys: list[ApiKeyConfig] = []
    key_ids: set[str] = set()
    for index, raw_key in enumerate(raw_keys):
        item = _mapping(raw_key, f"api.keys[{index}]")
        key_id = _string(item.get("id"), f"api.keys[{index}].id")
        if key_id in key_ids:
            raise ConfigError(f"duplicate API key id: {key_id}")
        key_ids.add(key_id)
        raw_scopes = item.get("scopes")
        if not isinstance(raw_scopes, Sequence) or isinstance(raw_scopes, str):
            raise ConfigError(f"api.keys[{index}].scopes must be an array")
        scopes = frozenset(
            _string(scope, f"api.keys[{index}].scopes") for scope in raw_scopes
        )
        if not scopes:
            raise ConfigError(f"api.keys[{index}].scopes must not be empty")
        api_keys.append(
            ApiKeyConfig(
                key_id,
                _secret(item.get("secret"), f"api.keys[{index}].secret"),
                scopes,
            )
        )
    api = ApiConfig(
        keys=tuple(api_keys),
        heartbeat_interval=_number(
            api_data.get("heartbeat_interval", 20.0),
            "api.heartbeat_interval",
        ),
        event_history_size=_integer(
            api_data.get("event_history_size", 1024),
            "api.event_history_size",
        ),
        client_queue_size=_integer(
            api_data.get("client_queue_size", 256),
            "api.client_queue_size",
        ),
    )

    state_data = _mapping(root.get("state"), "state")
    state = StateConfig(
        type=_string(state_data.get("type", "memory"), "state.type"),
        path=_string(state_data.get("path", "data/gateway-state.db"), "state.path"),
    )
    if state.type not in {"memory", "sqlite"}:
        raise ConfigError("state.type must be memory or sqlite")

    secrets_data = _mapping(root.get("secrets"), "secrets")
    secrets = DynamicSecretsConfig(
        type=_string(secrets_data.get("type", "memory"), "secrets.type"),
        path=_string(
            secrets_data.get("path", "data/gateway-secrets.json"),
            "secrets.path",
        ),
    )
    if secrets.type not in {"memory", "encrypted_file"}:
        raise ConfigError("secrets.type must be memory or encrypted_file")

    media_data = _mapping(root.get("media"), "media")
    media = MediaConfig(
        type=_string(media_data.get("type", "memory"), "media.type"),
        path=_string(media_data.get("path", "data/media"), "media.path"),
        max_upload_size=_integer(
            media_data.get("max_upload_size", 20 * 1024 * 1024),
            "media.max_upload_size",
        ),
        ttl_seconds=_number(
            media_data.get("ttl_seconds", 3600.0),
            "media.ttl_seconds",
        ),
    )
    if media.type not in {"memory", "file"}:
        raise ConfigError("media.type must be memory or file")
    return GatewayConfig(
        source=source,
        server=server,
        adapters=tuple(adapters),
        api=api,
        state=state,
        secrets=secrets,
        media=media,
    )

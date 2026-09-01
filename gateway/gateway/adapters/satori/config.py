"""Satori adapter-owned configuration."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SatoriConfig:
    api_base_url: str
    endpoint: str
    token_env: str | None
    heartbeat_interval: float
    reconnect_max_delay: float
    request_timeout: float

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "SatoriConfig":
        api_base_url = config.get("api_base_url", "http://localhost:5140/satori/v1")
        endpoint = config.get("endpoint", "ws://localhost:5140/satori/v1/events")
        if not isinstance(api_base_url, str) or not api_base_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError("Satori api_base_url must be HTTP(S)")
        if not isinstance(endpoint, str) or not endpoint.startswith(
            ("ws://", "wss://")
        ):
            raise ValueError("Satori endpoint must be WebSocket URL")
        token = config.get("token")
        token_env: str | None = None
        if token is not None:
            if (
                not isinstance(token, Mapping)
                or set(token) != {"env"}
                or not isinstance(token.get("env"), str)
                or not token["env"].strip()
            ):
                raise ValueError("Satori token must be an environment reference")
            token_env = token["env"]
        values: dict[str, float] = {}
        for name, default in {
            "heartbeat_interval": 10.0,
            "reconnect_max_delay": 30.0,
            "request_timeout": 30.0,
        }.items():
            value = config.get(name, default)
            if (
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"Satori {name} must be positive")
            values[name] = float(value)
        return cls(api_base_url.rstrip("/"), endpoint, token_env, **values)

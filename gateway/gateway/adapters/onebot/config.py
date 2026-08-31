"""OneBot adapter-owned configuration."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class OneBotConfig:
    """Configure forward or reverse OneBot v11 WebSocket transport.

    Args:
        mode: `websocket` for a forward client or `reverse_websocket` for the
            aiocqhttp-compatible reverse server.
        endpoint: Forward WebSocket URL.
        host: Reverse WebSocket bind host.
        port: Reverse WebSocket bind port.
        token_env: Environment variable containing the access token.
        action_timeout: Action response timeout in seconds.
        reconnect_max_delay: Maximum forward reconnect delay in seconds.
    """

    mode: str
    endpoint: str | None
    host: str
    port: int
    token_env: str | None
    action_timeout: float
    reconnect_max_delay: float

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "OneBotConfig":
        """Parse adapter-owned configuration.

        Args:
            config: Raw adapter configuration.

        Returns:
            Validated OneBot configuration.

        Raises:
            ValueError: If mode, endpoint, token reference, or limits are invalid.
        """
        mode = config.get("mode", "websocket")
        if mode not in {"websocket", "reverse_websocket"}:
            raise ValueError("OneBot mode must be websocket or reverse_websocket")
        endpoint = config.get("endpoint")
        if mode == "websocket" and (
            not isinstance(endpoint, str)
            or not endpoint.startswith(("ws://", "wss://"))
        ):
            raise ValueError(
                "OneBot websocket mode requires a ws:// or wss:// endpoint"
            )
        host = config.get("host", "127.0.0.1")
        port = config.get("port", 6199)
        if not isinstance(host, str) or not host.strip():
            raise ValueError("OneBot reverse host must not be empty")
        if (
            not isinstance(port, int)
            or isinstance(port, bool)
            or not 1 <= port <= 65535
        ):
            raise ValueError("OneBot reverse port is invalid")
        token_value = config.get("token")
        token_env: str | None = None
        if token_value is not None:
            if (
                not isinstance(token_value, Mapping)
                or set(token_value) != {"env"}
                or not isinstance(token_value.get("env"), str)
                or not token_value["env"].strip()
            ):
                raise ValueError("OneBot token must be an environment reference")
            token_env = token_value["env"]
        action_timeout = config.get("action_timeout", 30.0)
        reconnect_max_delay = config.get("reconnect_max_delay", 30.0)
        if (
            not isinstance(action_timeout, int | float)
            or isinstance(action_timeout, bool)
            or action_timeout <= 0
        ):
            raise ValueError("OneBot action_timeout must be positive")
        if (
            not isinstance(reconnect_max_delay, int | float)
            or isinstance(reconnect_max_delay, bool)
            or reconnect_max_delay <= 0
        ):
            raise ValueError("OneBot reconnect_max_delay must be positive")
        return cls(
            mode=mode,
            endpoint=endpoint if isinstance(endpoint, str) else None,
            host=host,
            port=port,
            token_env=token_env,
            action_timeout=float(action_timeout),
            reconnect_max_delay=float(reconnect_max_delay),
        )

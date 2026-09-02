"""Strict local-only Bridge configuration."""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    gateway_url: str
    api_key_env: str
    family: str | None
    event_type: str | None
    mode: str
    command: tuple[str, ...]
    agent_url: str | None
    session_path: Path
    max_concurrency: int = 4
    max_pending: int = 64
    invoke_timeout: float = 900
    max_stdout_bytes: int = 1_048_576
    env_allowlist: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path) -> "BridgeConfig":
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        gateway, events, agent, sessions, runtime = (
            value.get(key, {})
            for key in ("gateway", "events", "agent", "sessions", "runtime")
        )
        command = tuple(agent.get("command", ()))
        mode = str(agent.get("mode", "command"))
        if (
            mode not in {"command", "http"}
            or not gateway.get("url")
            or not gateway.get("api_key_env")
        ):
            raise ValueError("invalid bridge configuration")
        if mode == "command" and not command:
            raise ValueError("command mode requires a non-empty argv list")
        if mode == "http" and not agent.get("url"):
            raise ValueError("http mode requires agent.url")
        max_concurrency = _positive_int(
            runtime.get("max_concurrency", 4), "max_concurrency"
        )
        max_pending = _positive_int(runtime.get("max_pending", 64), "max_pending")
        invoke_timeout = _positive_float(
            runtime.get("invoke_timeout", 900), "invoke_timeout"
        )
        max_stdout_bytes = _positive_int(
            runtime.get("max_stdout_bytes", 1_048_576), "max_stdout_bytes"
        )
        return cls(
            str(gateway["url"]),
            str(gateway["api_key_env"]),
            events.get("family"),
            events.get("event_type"),
            mode,
            command,
            agent.get("url"),
            (path.parent / str(sessions.get("path", "agent-sessions.db"))).resolve(),
            max_concurrency,
            max_pending,
            invoke_timeout,
            max_stdout_bytes,
            tuple(agent.get("env_allowlist", ())),
        )


def _positive_int(value: object, name: str) -> int:
    """Parse one strictly positive integer configuration value."""
    if isinstance(value, bool):
        raise ValueError(f"runtime.{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"runtime.{name} must be a positive integer") from exc
    if parsed <= 0 or str(parsed) != str(value).strip():
        raise ValueError(f"runtime.{name} must be a positive integer")
    return parsed


def _positive_float(value: object, name: str) -> float:
    """Parse one finite, strictly positive runtime duration."""
    if isinstance(value, bool):
        raise ValueError(f"runtime.{name} must be a positive number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"runtime.{name} must be a positive number") from exc
    if not isfinite(parsed) or parsed <= 0:
        raise ValueError(f"runtime.{name} must be a positive number")
    return parsed

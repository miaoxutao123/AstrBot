"""Strict local-only Bridge configuration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    invoke_timeout: float = 900
    max_stdout_bytes: int = 1_048_576
    env_allowlist: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path) -> "BridgeConfig":
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        gateway, events, agent, sessions, runtime = (value.get(key, {}) for key in ("gateway", "events", "agent", "sessions", "runtime"))
        command = tuple(agent.get("command", ()))
        mode = str(agent.get("mode", "command"))
        if mode not in {"command", "http"} or not gateway.get("url") or not gateway.get("api_key_env"):
            raise ValueError("invalid bridge configuration")
        if mode == "command" and not command:
            raise ValueError("command mode requires a non-empty argv list")
        if mode == "http" and not agent.get("url"):
            raise ValueError("http mode requires agent.url")
        return cls(str(gateway["url"]), str(gateway["api_key_env"]), events.get("family"), events.get("event_type"), mode, command, agent.get("url"),
                   (path.parent / str(sessions.get("path", "agent-sessions.db"))).resolve(), int(runtime.get("max_concurrency", 4)), float(runtime.get("invoke_timeout", 900)), int(runtime.get("max_stdout_bytes", 1_048_576)), tuple(agent.get("env_allowlist", ())))

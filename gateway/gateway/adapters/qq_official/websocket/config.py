"""QQ Official WebSocket configuration."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..common.config_common import QQOfficialCommonConfig


@dataclass(frozen=True, slots=True)
class QQOfficialWebSocketConfig:
    common: QQOfficialCommonConfig
    intents: int
    reconnect_max_delay: float
    heartbeat_timeout: float

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "QQOfficialWebSocketConfig":
        intents = config.get("intents", 1 << 25 | 1 << 30 | 1 << 12 | 1 << 9)
        if not isinstance(intents, int) or isinstance(intents, bool) or intents <= 0:
            raise ValueError("QQ Official intents must be a positive integer")
        values: dict[str, float] = {}
        for name, default in {
            "reconnect_max_delay": 30.0,
            "heartbeat_timeout": 45.0,
        }.items():
            value = config.get(name, default)
            if (
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"QQ Official {name} must be positive")
            values[name] = float(value)
        return cls(QQOfficialCommonConfig.from_mapping(config), intents, **values)

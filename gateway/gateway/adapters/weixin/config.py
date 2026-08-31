"""Weixin OC adapter-owned configuration."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WeixinConfig:
    base_url: str
    cdn_base_url: str
    bot_type: str
    qr_poll_interval: float
    long_poll_timeout: float
    api_timeout: float
    reconnect_max_delay: float

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "WeixinConfig":
        base_url = config.get("base_url", "https://ilinkai.weixin.qq.com")
        cdn_url = config.get("cdn_base_url", "https://novac2c.cdn.weixin.qq.com/c2c")
        for name, value in (("base_url", base_url), ("cdn_base_url", cdn_url)):
            if not isinstance(value, str) or not value.startswith(
                ("http://", "https://")
            ):
                raise ValueError(f"Weixin {name} must be an HTTP(S) URL")
        timings: dict[str, float] = {}
        for name, default in {
            "qr_poll_interval": 1.0,
            "long_poll_timeout": 35.0,
            "api_timeout": 120.0,
            "reconnect_max_delay": 30.0,
        }.items():
            value = config.get(name, default)
            if (
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"Weixin {name} must be positive")
            timings[name] = float(value)
        bot_type = config.get("bot_type", "3")
        if not isinstance(bot_type, str) or not bot_type.strip():
            raise ValueError("Weixin bot_type must not be empty")
        return cls(base_url.rstrip("/"), cdn_url.rstrip("/"), bot_type, **timings)

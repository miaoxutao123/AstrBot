"""Telegram adapter-owned configuration."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    """Configure Telegram Bot API polling.

    Args:
        token_env: Environment variable containing the bot token.
        base_url: Bot API method base URL.
        file_base_url: Bot API file base URL.
        polling_timeout: Long-poll timeout in seconds.
        reconnect_max_delay: Maximum rebuild delay in seconds.
        health_interval: Bot API health probe interval in seconds.
        media_group_timeout: Album debounce delay in seconds.
        media_group_max_wait: Maximum album collection time in seconds.
    """

    token_env: str
    base_url: str
    file_base_url: str
    polling_timeout: float
    reconnect_max_delay: float
    health_interval: float
    media_group_timeout: float
    media_group_max_wait: float

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "TelegramConfig":
        """Parse adapter-owned configuration.

        Args:
            config: Raw adapter configuration.

        Returns:
            Validated Telegram configuration.

        Raises:
            ValueError: If token, URL, or timing values are invalid.
        """
        token = config.get("token")
        if (
            not isinstance(token, Mapping)
            or set(token) != {"env"}
            or not isinstance(token.get("env"), str)
            or not token["env"].strip()
        ):
            raise ValueError("Telegram token must be an environment reference")
        base_url = config.get("base_url", "https://api.telegram.org/bot")
        file_base_url = config.get(
            "file_base_url",
            "https://api.telegram.org/file/bot",
        )
        for name, value in (("base_url", base_url), ("file_base_url", file_base_url)):
            if not isinstance(value, str) or not value.startswith(
                ("http://", "https://")
            ):
                raise ValueError(f"Telegram {name} must be an HTTP(S) URL")

        values: dict[str, float] = {}
        defaults = {
            "polling_timeout": 30.0,
            "reconnect_max_delay": 30.0,
            "health_interval": 15.0,
            "media_group_timeout": 1.0,
            "media_group_max_wait": 10.0,
        }
        for name, default in defaults.items():
            value = config.get(name, default)
            if (
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"Telegram {name} must be positive")
            values[name] = float(value)
        if values["media_group_max_wait"] < values["media_group_timeout"]:
            raise ValueError(
                "Telegram media_group_max_wait must not be shorter than timeout"
            )
        return cls(
            token_env=token["env"],
            base_url=base_url,
            file_base_url=file_base_url,
            **values,
        )

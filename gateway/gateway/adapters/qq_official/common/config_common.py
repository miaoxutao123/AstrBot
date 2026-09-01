"""Configuration shared by future QQ Official transports."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def env_reference(config: Mapping[str, Any], name: str) -> str:
    value = config.get(name)
    if (
        not isinstance(value, Mapping)
        or set(value) != {"env"}
        or not isinstance(value.get("env"), str)
        or not value["env"].strip()
    ):
        raise ValueError(f"QQ Official {name} must be an environment reference")
    return str(value["env"])


@dataclass(frozen=True, slots=True)
class QQOfficialCommonConfig:
    app_id_env: str
    secret_env: str
    api_base_url: str
    auth_url: str
    request_timeout: float

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "QQOfficialCommonConfig":
        api = config.get("api_base_url", "https://api.sgroup.qq.com")
        auth = config.get("auth_url", "https://bots.qq.com/app/getAppAccessToken")
        if not isinstance(api, str) or not api.startswith(("http://", "https://")):
            raise ValueError("QQ Official api_base_url must be HTTP(S)")
        if not isinstance(auth, str) or not auth.startswith(("http://", "https://")):
            raise ValueError("QQ Official auth_url must be HTTP(S)")
        timeout = config.get("request_timeout", 30.0)
        if (
            not isinstance(timeout, int | float)
            or isinstance(timeout, bool)
            or timeout <= 0
        ):
            raise ValueError("QQ Official request_timeout must be positive")
        return cls(
            env_reference(config, "app_id"),
            env_reference(config, "secret"),
            api.rstrip("/"),
            auth,
            float(timeout),
        )

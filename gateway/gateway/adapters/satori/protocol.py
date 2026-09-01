"""Satori signaling and adapter-owned routing identity."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote

EVENT = 0
PING = 1
PONG = 2
IDENTIFY = 3
READY = 4
META = 5


@dataclass(frozen=True, slots=True)
class SatoriLogin:
    platform: str
    self_id: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SatoriLogin | None":
        platform = value.get("platform")
        user = value.get("user")
        self_id = user.get("id") if isinstance(user, Mapping) else None
        if (
            not isinstance(platform, str)
            or not platform
            or not isinstance(self_id, str)
            or not self_id
        ):
            return None
        return cls(platform, self_id)


def endpoint_id(login: SatoriLogin, channel_id: str) -> str:
    """Encode login/account routing without exposing structure to Core."""
    return f"account:{quote(login.platform, safe='')}:{quote(login.self_id, safe='')}/channel:{quote(channel_id, safe='')}"


def parse_endpoint(value: str) -> tuple[SatoriLogin, str]:
    try:
        account, channel = value.split("/channel:", 1)
        prefix, platform, self_id = account.split(":", 2)
    except ValueError as exc:
        raise ValueError("invalid Satori endpoint_id") from exc
    if prefix != "account" or not platform or not self_id or not channel:
        raise ValueError("invalid Satori endpoint_id")
    return SatoriLogin(unquote(platform), unquote(self_id)), unquote(channel)

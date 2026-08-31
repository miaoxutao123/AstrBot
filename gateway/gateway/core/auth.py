"""Generic interactive authentication contract for adapters."""

from dataclasses import dataclass
from enum import Enum


class AdapterAuthStatus(str, Enum):
    """Stable adapter authentication states exposed by the Gateway API."""

    NOT_REQUIRED = "not_required"
    LOGGED_OUT = "logged_out"
    WAITING_USER = "waiting_user"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AuthChallenge:
    """Transport-neutral interactive authentication challenge."""

    qr_uri: str | None = None
    media_id: str | None = None
    verification_code: str | None = None
    instructions: str | None = None


@dataclass(frozen=True, slots=True)
class AdapterAuthInfo:
    """Public authentication state for one adapter instance."""

    status: AdapterAuthStatus
    challenge: AuthChallenge | None = None
    reason: str | None = None

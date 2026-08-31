"""Stable Gateway error model."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GatewayErrorCode(str, Enum):
    """Machine-readable error codes shared by Core and future APIs."""

    ADAPTER_NOT_FOUND = "ADAPTER_NOT_FOUND"
    ADAPTER_OFFLINE = "ADAPTER_OFFLINE"
    ENDPOINT_NOT_FOUND = "ENDPOINT_NOT_FOUND"
    CAPABILITY_NOT_SUPPORTED = "CAPABILITY_NOT_SUPPORTED"
    INVALID_COMMAND = "INVALID_COMMAND"
    AUTH_FAILED = "AUTH_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class GatewayError:
    """Serializable error returned across the Gateway boundary.

    Args:
        code: Stable machine-readable error code.
        message: Safe human-readable message.
        retryable: Whether retrying may succeed without changing the command.
        details: Non-sensitive structured context.
    """

    code: GatewayErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


class GatewayException(Exception):
    """Internal exception carrying a stable public error.

    Args:
        error: Public error safe to return to a caller.
    """

    def __init__(self, error: GatewayError) -> None:
        super().__init__(error.message)
        self.error = error

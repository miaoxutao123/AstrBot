"""Stable API-layer exceptions and status mapping."""

from gateway.core import GatewayError


class GatewayApiError(Exception):
    """Carry a safe Gateway error and HTTP status.

    Args:
        status_code: HTTP response status.
        error: Stable error safe to serialize.
    """

    def __init__(self, status_code: int, error: GatewayError) -> None:
        super().__init__(error.message)
        self.status_code = status_code
        self.error = error

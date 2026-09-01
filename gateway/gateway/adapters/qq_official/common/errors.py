"""Safe QQ Official errors."""


class QQOfficialError(Exception):
    """Base QQ Official error."""


class QQOfficialAuthenticationError(QQOfficialError):
    """Static or access credentials were rejected."""


class QQOfficialNetworkError(QQOfficialError):
    """Gateway or REST network failed."""


class QQOfficialRequestError(QQOfficialError):
    """Command or response was invalid."""


class QQOfficialDeliveryError(QQOfficialError):
    """QQ accepted transport but rejected message delivery."""


class QQOfficialTimeoutError(QQOfficialError):
    """An operation exceeded its deadline."""


class QQOfficialRateLimitError(QQOfficialError):
    """QQ rate limited an operation."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after

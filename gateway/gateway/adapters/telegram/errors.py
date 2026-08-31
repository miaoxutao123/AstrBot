"""Telegram transport errors contained by AdapterRuntime."""


class TelegramError(Exception):
    """Base Telegram transport error."""


class TelegramAuthenticationError(TelegramError):
    """Telegram rejected the bot token or bot access."""


class TelegramNetworkError(TelegramError):
    """Telegram could not be reached temporarily."""


class TelegramRateLimitError(TelegramError):
    """Telegram requested a bounded retry delay.

    Args:
        retry_after: Requested delay in seconds.
    """

    def __init__(self, retry_after: float) -> None:
        super().__init__("Telegram rate limit was reached")
        self.retry_after = retry_after


class TelegramRequestError(TelegramError):
    """Telegram rejected an invalid operation."""

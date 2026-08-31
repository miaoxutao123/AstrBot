"""OneBot transport-specific errors contained by AdapterRuntime."""


class OneBotError(Exception):
    """Base OneBot transport error."""


class OneBotAuthenticationError(OneBotError):
    """OneBot rejected the configured access token."""


class OneBotDisconnectedError(OneBotError):
    """OneBot is not connected to an action channel."""


class OneBotActionError(OneBotError):
    """OneBot returned a failed action response."""

"""Safe Satori transport errors."""


class SatoriError(Exception):
    """Base Satori error contained by AdapterRuntime."""


class SatoriAuthenticationError(SatoriError):
    """Authentication was rejected."""


class SatoriNetworkError(SatoriError):
    """WebSocket or HTTP transport failed."""


class SatoriRequestError(SatoriError):
    """Satori rejected a protocol operation."""

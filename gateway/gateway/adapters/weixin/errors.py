"""Safe Weixin transport errors."""


class WeixinError(Exception):
    """Base safe Weixin error."""


class WeixinAuthenticationError(WeixinError):
    """Stored Weixin session is no longer valid."""


class WeixinNetworkError(WeixinError):
    """Transient Weixin network failure."""


class WeixinRequestError(WeixinError):
    """Rejected or malformed Weixin request."""

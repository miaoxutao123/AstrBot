"""In-memory API key authentication and scope authorization."""

import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from gateway.control_plane import AgentRegistry
from gateway.core import GatewayError, GatewayErrorCode

from .errors import GatewayApiError


@dataclass(frozen=True, slots=True)
class ApiKey:
    """Configure one API key without persistence concerns.

    Args:
        id: Non-secret key identifier used in audit context.
        secret: Secret bearer value. It must never be logged.
        scopes: Authorization scopes granted to callers using this key.

    Raises:
        ValueError: If the identifier, secret, or scopes are empty.
    """

    id: str
    secret: str
    scopes: frozenset[str]

    def __post_init__(self) -> None:
        """Validate API key configuration.

        Raises:
            ValueError: If the identifier, secret, or scopes are empty.
        """
        if not self.id or not self.id.strip():
            raise ValueError("API key id must not be empty")
        if not self.secret:
            raise ValueError("API key secret must not be empty")
        if not self.scopes:
            raise ValueError("API key scopes must not be empty")


@dataclass(frozen=True, slots=True)
class ApiPrincipal:
    """Authenticated caller identity.

    Args:
        key_id: Non-secret API key identifier.
        scopes: Scopes granted to this caller.
    """

    key_id: str
    scopes: frozenset[str]

    def allows(self, scope: str) -> bool:
        """Return whether this principal has a scope.

        Args:
            scope: Required scope.

        Returns:
            ``True`` for the exact scope or wildcard administration scope.
        """
        return "*" in self.scopes or scope in self.scopes


class ApiKeyStore:
    """Authenticate configured API keys using constant-time comparison.

    Args:
        keys: API keys configured by the Gateway host.
    """

    def __init__(
        self, keys: Sequence[ApiKey], agents: AgentRegistry | None = None
    ) -> None:
        self._keys = tuple(keys)
        self._agents = agents

    def authenticate(self, headers: Mapping[str, str]) -> ApiPrincipal:
        """Authenticate an Authorization or X-API-Key header.

        Args:
            headers: Case-insensitive HTTP or WebSocket headers.

        Returns:
            Authenticated API principal.

        Raises:
            GatewayApiError: If the credential is missing or invalid.
        """
        authorization = headers.get("authorization", "")
        token = ""
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        if not token:
            token = headers.get("x-api-key", "").strip()
        if not token:
            raise GatewayApiError(
                401,
                GatewayError(
                    GatewayErrorCode.AUTH_FAILED,
                    "API key is required",
                ),
            )
        for api_key in self._keys:
            if secrets.compare_digest(token, api_key.secret):
                return ApiPrincipal(api_key.id, api_key.scopes)
        if self._agents is not None and (agent := self._agents.authenticate(token)):
            return ApiPrincipal(agent[0], agent[1])
        raise GatewayApiError(
            401,
            GatewayError(
                GatewayErrorCode.AUTH_FAILED,
                "API key is invalid",
            ),
        )

    def require(self, principal: ApiPrincipal, scope: str) -> None:
        """Require one caller scope.

        Args:
            principal: Authenticated caller.
            scope: Required scope.

        Raises:
            GatewayApiError: If the caller lacks the scope.
        """
        if not principal.allows(scope):
            raise GatewayApiError(
                403,
                GatewayError(
                    GatewayErrorCode.AUTH_FAILED,
                    f"API key lacks required scope: {scope}",
                ),
            )

"""Environment-backed secret resolution."""

import os
from collections.abc import Mapping

from .schema import SecretReference


class EnvironmentSecretResolver:
    """Resolve secrets without retaining or logging their values.

    Args:
        environment: Optional environment mapping for tests.
    """

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment = os.environ if environment is None else environment

    def get(self, key: str) -> str | None:
        """Resolve an environment variable by name.

        Args:
            key: Environment variable name.

        Returns:
            Secret value when present.
        """
        return self._environment.get(key)

    def require(self, reference: SecretReference) -> str:
        """Resolve a required secret reference.

        Args:
            reference: Environment-backed secret reference.

        Returns:
            Non-empty secret value.

        Raises:
            ValueError: If the referenced environment variable is absent.
        """
        value = self.get(reference.env)
        if value is None or not value:
            raise ValueError(
                f"required secret environment variable is missing: {reference.env}"
            )
        return value

"""Adapter and endpoint capability declarations."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Capability:
    """Describe an operation supported by an adapter or endpoint.

    Args:
        name: Stable capability identifier.
        version: Capability contract version.
        schema: Optional input schema for discovery clients.

    Raises:
        ValueError: If the name or version is empty.
    """

    name: str
    version: str = "1"
    schema: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate the declaration.

        Raises:
            ValueError: If the name or version is empty.
        """
        if not self.name or not self.name.strip():
            raise ValueError("capability name must not be empty")
        if not self.version or not self.version.strip():
            raise ValueError("capability version must not be empty")

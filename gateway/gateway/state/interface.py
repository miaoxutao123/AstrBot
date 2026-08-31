"""Minimal adapter state persistence contract."""

from abc import ABC, abstractmethod
from typing import Any


class AdapterStateStore(ABC):
    """Persist JSON-compatible adapter state by key."""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Read one value.

        Args:
            key: Store key.

        Returns:
            Stored JSON-compatible value or ``None``.
        """
        raise NotImplementedError

    @abstractmethod
    async def set(self, key: str, value: Any) -> None:
        """Store one JSON-compatible value.

        Args:
            key: Store key.
            value: JSON-compatible value.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete one value.

        Args:
            key: Store key.

        Returns:
            Whether a value existed.
        """
        raise NotImplementedError

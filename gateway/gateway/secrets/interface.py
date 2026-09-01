"""Dynamic adapter credential persistence contract."""

from abc import ABC, abstractmethod


class AdapterSecretStore(ABC):
    """Persist only secret string values by key."""

    @abstractmethod
    async def get(self, key: str) -> str | None:
        """Return one secret value or ``None``."""
        raise NotImplementedError

    @abstractmethod
    async def set(self, key: str, value: str) -> None:
        """Persist one non-empty string secret."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete one secret and return whether it existed."""
        raise NotImplementedError

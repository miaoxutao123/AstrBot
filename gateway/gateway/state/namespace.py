"""Adapter-owned namespace view over a host state store."""

from typing import Any

from .interface import AdapterStateStore


class NamespacedStateStore(AdapterStateStore):
    """Restrict an adapter to its automatically assigned key prefix.

    Args:
        store: Host-owned underlying state store.
        adapter_id: Configured adapter instance identifier.
    """

    def __init__(self, store: AdapterStateStore, adapter_id: str) -> None:
        if not adapter_id or "/" in adapter_id or "\\" in adapter_id:
            raise ValueError("adapter state namespace is invalid")
        self._store = store
        self._prefix = f"adapter/{adapter_id}/"

    def _key(self, key: str) -> str:
        if (
            not key
            or key.startswith(("/", "\\"))
            or ".." in key.split("/")
            or "\\" in key
        ):
            raise ValueError("adapter state key is invalid")
        return f"{self._prefix}{key}"

    async def get(self, key: str) -> Any | None:
        """Read a value within this adapter namespace.

        Args:
            key: Adapter-local key.

        Returns:
            Stored value or ``None``.
        """
        return await self._store.get(self._key(key))

    async def set(self, key: str, value: Any) -> None:
        """Store a value within this adapter namespace.

        Args:
            key: Adapter-local key.
            value: JSON-compatible value.
        """
        await self._store.set(self._key(key), value)

    async def delete(self, key: str) -> bool:
        """Delete a value within this adapter namespace.

        Args:
            key: Adapter-local key.

        Returns:
            Whether a value existed.
        """
        return await self._store.delete(self._key(key))

"""In-memory adapter credential store."""

import asyncio

from .interface import AdapterSecretStore


class MemorySecretStore(AdapterSecretStore):
    """Keep dynamic credentials only for the process lifetime."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        async with self._lock:
            return self._values.get(key)

    async def set(self, key: str, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError("secret value must be a non-empty string")
        async with self._lock:
            self._values[key] = value

    async def delete(self, key: str) -> bool:
        async with self._lock:
            return self._values.pop(key, None) is not None

"""In-memory adapter state store."""

import asyncio
import json
from typing import Any

from .interface import AdapterStateStore


class MemoryStateStore(AdapterStateStore):
    """Store isolated JSON values in process memory."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        """Read one copied value.

        Args:
            key: Store key.

        Returns:
            Stored JSON-compatible value or ``None``.
        """
        async with self._lock:
            serialized = self._values.get(key)
        return None if serialized is None else json.loads(serialized)

    async def set(self, key: str, value: Any) -> None:
        """Store one JSON-compatible value.

        Args:
            key: Store key.
            value: JSON-compatible value.

        Raises:
            TypeError: If the value is not JSON-compatible.
        """
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        async with self._lock:
            self._values[key] = serialized

    async def delete(self, key: str) -> bool:
        """Delete one value.

        Args:
            key: Store key.

        Returns:
            Whether a value existed.
        """
        async with self._lock:
            return self._values.pop(key, None) is not None

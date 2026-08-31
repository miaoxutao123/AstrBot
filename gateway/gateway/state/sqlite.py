"""SQLite-backed adapter state store."""

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from .interface import AdapterStateStore


class SQLiteStateStore(AdapterStateStore):
    """Persist adapter state in a dedicated SQLite table.

    Args:
        path: Host-controlled SQLite database path.
    """

    def __init__(self, path: Path) -> None:
        self._path = path.resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._initialize()

    def _initialize(self) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS adapter_state ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def _read(self, key: str) -> str | None:
        with sqlite3.connect(self._path) as connection:
            row = connection.execute(
                "SELECT value FROM adapter_state WHERE key = ?",
                (key,),
            ).fetchone()
        return None if row is None else str(row[0])

    def _write(self, key: str, value: str) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "INSERT INTO adapter_state(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def _delete(self, key: str) -> bool:
        with sqlite3.connect(self._path) as connection:
            cursor = connection.execute(
                "DELETE FROM adapter_state WHERE key = ?",
                (key,),
            )
            return cursor.rowcount > 0

    async def get(self, key: str) -> Any | None:
        """Read one copied value.

        Args:
            key: Store key.

        Returns:
            Stored JSON-compatible value or ``None``.
        """
        async with self._lock:
            serialized = await asyncio.to_thread(self._read, key)
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
            await asyncio.to_thread(self._write, key, serialized)

    async def delete(self, key: str) -> bool:
        """Delete one value.

        Args:
            key: Store key.

        Returns:
            Whether a value existed.
        """
        async with self._lock:
            return await asyncio.to_thread(self._delete, key)

"""Small Bridge-owned SQLite mapping store; never stores Agent memory."""

import sqlite3
from pathlib import Path


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection = sqlite3.connect(path)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS sessions (key TEXT PRIMARY KEY, external_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )

    def get(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT external_id FROM sessions WHERE key=?", (key,)
        ).fetchone()
        return None if row is None else str(row[0])

    def put(self, key: str, external_id: str) -> None:
        self._connection.execute(
            "INSERT INTO sessions(key, external_id) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET external_id=excluded.external_id, updated_at=CURRENT_TIMESTAMP",
            (key, external_id),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

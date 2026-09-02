"""SQLite source-of-truth for WebUI-managed adapter instances."""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class ManagedAdapterStore:
    """Persist managed adapter configuration without retaining plaintext secrets."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # FastAPI's TestClient and production ASGI workers may enter the
        # lifespan and request handlers from different threads.
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS managed_adapters (adapter_id TEXT PRIMARY KEY, adapter_type TEXT NOT NULL, enabled INTEGER NOT NULL, config_json TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL)"
        )

    def list(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT adapter_id, adapter_type, enabled, config_json, created_at, updated_at FROM managed_adapters ORDER BY adapter_id"
        ).fetchall()
        return [
            {
                "id": row[0],
                "type": row[1],
                "enabled": bool(row[2]),
                "config": json.loads(row[3]),
                "source": "managed",
                "created_at": row[4],
                "updated_at": row[5],
            }
            for row in rows
        ]

    def put(
        self, adapter_id: str, adapter_type: str, enabled: bool, config: dict[str, Any]
    ) -> dict[str, Any]:
        if not adapter_id or not adapter_type:
            raise ValueError("adapter id and type are required")
        now = time.time()
        self._connection.execute(
            "INSERT INTO managed_adapters VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(adapter_id) DO UPDATE SET adapter_type=excluded.adapter_type, enabled=excluded.enabled, config_json=excluded.config_json, updated_at=excluded.updated_at",
            (adapter_id, adapter_type, enabled, json.dumps(config), now, now),
        )
        self._connection.commit()
        return next(item for item in self.list() if item["id"] == adapter_id)

    def delete(self, adapter_id: str) -> None:
        self._connection.execute(
            "DELETE FROM managed_adapters WHERE adapter_id=?", (adapter_id,)
        )
        self._connection.commit()

    def patch(self, adapter_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        current = next((item for item in self.list() if item["id"] == adapter_id), None)
        if current is None:
            raise ValueError("managed adapter was not found")
        return self.put(
            adapter_id,
            str(changes.get("type", current["type"])),
            bool(changes.get("enabled", current["enabled"])),
            dict(changes.get("config", current["config"])),
        )

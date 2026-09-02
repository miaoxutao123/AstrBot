"""SQLite-backed external Agent enrollment and credential registry.

This module deliberately owns identity and access only; it never starts or
executes an Agent Runtime.
"""

import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any


class AgentRegistry:
    """Persist one-time enrollment and independently revocable Agent keys."""

    def __init__(self, path: Path, *, online_after: float = 60) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._online_after = online_after
        self._connection.executescript("""
        CREATE TABLE IF NOT EXISTS enrollments (id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, name_hint TEXT, scopes TEXT NOT NULL, expires_at REAL NOT NULL, consumed_at REAL);
        CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, display_name TEXT NOT NULL, instance_id TEXT, metadata TEXT NOT NULL, scopes TEXT NOT NULL, registered_at REAL NOT NULL, last_seen_at REAL, revoked_at REAL);
        CREATE TABLE IF NOT EXISTS credentials (id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, secret_hash TEXT NOT NULL, scopes TEXT NOT NULL, created_at REAL NOT NULL, revoked_at REAL);
        """)

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def create_enrollment(
        self, name_hint: str, scopes: list[str], ttl_seconds: float
    ) -> dict[str, Any]:
        if ttl_seconds <= 0 or ttl_seconds > 3600:
            raise ValueError("ttl_seconds must be between 1 and 3600")
        token = f"enr_{secrets.token_urlsafe(32)}"
        enrollment_id = f"enr_{secrets.token_hex(10)}"
        expires_at = time.time() + ttl_seconds
        self._connection.execute(
            "INSERT INTO enrollments VALUES (?, ?, ?, ?, ?, NULL)",
            (
                enrollment_id,
                self._hash(token),
                name_hint,
                json.dumps(scopes),
                expires_at,
            ),
        )
        self._connection.commit()
        return {
            "id": enrollment_id,
            "token": token,
            "expires_at": expires_at,
            "scopes": scopes,
        }

    def register(self, token: str, descriptor: dict[str, Any]) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT id, scopes, expires_at, consumed_at FROM enrollments WHERE token_hash=?",
            (self._hash(token),),
        ).fetchone()
        if row is None or row[3] is not None or float(row[2]) < time.time():
            raise ValueError("enrollment token is invalid, expired, or consumed")
        agent_id, credential_id = (
            f"agt_{secrets.token_hex(10)}",
            f"cred_{secrets.token_hex(10)}",
        )
        key, now = f"ag_{secrets.token_urlsafe(32)}", time.time()
        scopes = json.loads(str(row[1]))
        self._connection.execute(
            "UPDATE enrollments SET consumed_at=? WHERE id=?", (now, row[0])
        )
        self._connection.execute(
            "INSERT INTO agents VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)",
            (
                agent_id,
                str(descriptor.get("display_name", "Unnamed Agent")),
                descriptor.get("instance_id"),
                json.dumps(descriptor),
                json.dumps(scopes),
                now,
            ),
        )
        self._connection.execute(
            "INSERT INTO credentials VALUES (?, ?, ?, ?, ?, NULL)",
            (credential_id, agent_id, self._hash(key), json.dumps(scopes), now),
        )
        self._connection.commit()
        return {"agent_id": agent_id, "api_key": key, "scopes": scopes}

    def authenticate(self, key: str) -> tuple[str, frozenset[str]] | None:
        row = self._connection.execute(
            "SELECT agent_id, scopes FROM credentials WHERE secret_hash=? AND revoked_at IS NULL",
            (self._hash(key),),
        ).fetchone()
        return (
            None if row is None else (str(row[0]), frozenset(json.loads(str(row[1]))))
        )

    def heartbeat(self, agent_id: str, metadata: dict[str, Any]) -> None:
        encoded = json.dumps(metadata)
        if len(encoded.encode()) > 16 * 1024:
            raise ValueError("heartbeat metadata exceeds 16 KiB")
        updated = self._connection.execute(
            "UPDATE agents SET last_seen_at=?, metadata=? WHERE id=? AND revoked_at IS NULL",
            (time.time(), encoded, agent_id),
        )
        self._connection.commit()
        if updated.rowcount != 1:
            raise ValueError("agent is revoked or unknown")

    def list_agents(self) -> list[dict[str, Any]]:
        now = time.time()
        rows = self._connection.execute(
            "SELECT id, display_name, instance_id, metadata, scopes, registered_at, last_seen_at, revoked_at FROM agents ORDER BY registered_at"
        ).fetchall()
        return [
            {
                "id": row[0],
                "display_name": row[1],
                "instance_id": row[2],
                "metadata": json.loads(row[3]),
                "scopes": json.loads(row[4]),
                "registered_at": row[5],
                "last_seen_at": row[6],
                "status": "REVOKED"
                if row[7]
                else "ONLINE"
                if row[6] and now - row[6] <= self._online_after
                else "OFFLINE",
            }
            for row in rows
        ]

    def revoke(self, agent_id: str) -> None:
        now = time.time()
        self._connection.execute(
            "UPDATE agents SET revoked_at=? WHERE id=?", (now, agent_id)
        )
        self._connection.execute(
            "UPDATE credentials SET revoked_at=? WHERE agent_id=?", (now, agent_id)
        )
        self._connection.commit()

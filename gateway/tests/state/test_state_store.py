"""Adapter state namespace and SQLite persistence tests."""

from pathlib import Path

import pytest

from gateway.state import MemoryStateStore, NamespacedStateStore, SQLiteStateStore


@pytest.mark.asyncio
async def test_namespaces_prevent_cross_adapter_access() -> None:
    underlying = MemoryStateStore()
    first = NamespacedStateStore(underlying, "first")
    second = NamespacedStateStore(underlying, "second")

    await first.set("cursor", {"value": 1})

    assert await first.get("cursor") == {"value": 1}
    assert await second.get("cursor") is None
    with pytest.raises(ValueError, match="key is invalid"):
        await first.get("../second/cursor")


@pytest.mark.asyncio
async def test_sqlite_state_survives_store_recreation(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    first = NamespacedStateStore(SQLiteStateStore(path), "qq-main")
    await first.set("session", {"token": "opaque"})

    second = NamespacedStateStore(SQLiteStateStore(path), "qq-main")

    assert await second.get("session") == {"token": "opaque"}
    assert await second.delete("session")
    assert await second.get("session") is None

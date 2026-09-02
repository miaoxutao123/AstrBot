"""Managed adapter persistence and public-secret redaction tests."""

from pathlib import Path

from gateway.control_plane import ManagedAdapterStore, ManagedSecretStore
from gateway.secrets import MemorySecretStore


async def test_managed_secret_reference_never_contains_value(tmp_path: Path) -> None:
    secrets = ManagedSecretStore(MemorySecretStore())
    reference = await secrets.set("qq-main", "secret", "actual-secret")
    store = ManagedAdapterStore(tmp_path / "managed.db")
    stored = store.put("qq-main", "qq_official", True, {"secret": reference})
    assert stored["config"]["secret"] == reference
    assert "actual-secret" not in (tmp_path / "managed.db").read_bytes().decode(
        "latin1"
    )
    assert secrets.public(stored["config"]) == {"secret": {"configured": True}}

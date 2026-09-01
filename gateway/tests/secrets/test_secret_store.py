"""Dynamic credential store security and isolation tests."""

import base64
import json
from pathlib import Path
from typing import Any, cast

import pytest

from gateway.secrets import MemorySecretStore, NamespacedSecretStore
from gateway.secrets.encrypted_file import EncryptedFileSecretStore, SecretStoreError


def master_key(byte: int = 7) -> str:
    return base64.b64encode(bytes([byte]) * 32).decode()


async def test_memory_secret_store_accepts_only_strings() -> None:
    store = MemorySecretStore()
    await store.set("token", "secret")
    assert await store.get("token") == "secret"
    with pytest.raises(ValueError):
        await store.set("invalid", cast(Any, {"token": "secret"}))
    assert await store.delete("token")
    assert await store.get("token") is None


async def test_encrypted_file_round_trip_hides_plaintext(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    store = EncryptedFileSecretStore(path, master_key())
    await store.set("adapter/weixin-main/token", "raw-sensitive-token")

    contents = path.read_text(encoding="utf-8")
    assert "raw-sensitive-token" not in contents
    assert json.loads(contents)["version"] == 1
    restored = EncryptedFileSecretStore(path, master_key())
    assert await restored.get("adapter/weixin-main/token") == "raw-sensitive-token"


async def test_wrong_key_and_corrupted_ciphertext_fail_explicitly(
    tmp_path: Path,
) -> None:
    path = tmp_path / "secrets.json"
    store = EncryptedFileSecretStore(path, master_key())
    await store.set("adapter/a/token", "credential")

    with pytest.raises(SecretStoreError, match="authentication failed"):
        EncryptedFileSecretStore(path, master_key(8))

    document = json.loads(path.read_text(encoding="utf-8"))
    document["entries"]["adapter/a/token"]["ciphertext"] = "not-base64!"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SecretStoreError, match="authentication failed"):
        EncryptedFileSecretStore(path, master_key())


async def test_namespace_isolation() -> None:
    backend = MemorySecretStore()
    adapter_a = NamespacedSecretStore(backend, "adapter-a")
    adapter_b = NamespacedSecretStore(backend, "adapter-b")
    await adapter_a.set("token", "a-secret")
    await adapter_b.set("token", "b-secret")

    assert await adapter_a.get("token") == "a-secret"
    assert await adapter_b.get("token") == "b-secret"
    assert await backend.get("adapter/adapter-a/token") == "a-secret"
    assert await backend.get("adapter/adapter-b/token") == "b-secret"
    with pytest.raises(ValueError):
        await adapter_a.get("../adapter-b/token")

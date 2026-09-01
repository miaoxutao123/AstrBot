"""Versioned AES-GCM encrypted dynamic credential backend."""

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any

from Crypto.Cipher import AES

from .interface import AdapterSecretStore

FORMAT_VERSION = 1


class SecretStoreError(RuntimeError):
    """Explicit secret configuration, format, or decryption failure."""


def decode_master_key(value: str) -> bytes:
    """Decode a base64-encoded 256-bit master key."""
    try:
        key = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise SecretStoreError("Gateway master key must be valid base64") from exc
    if len(key) != 32:
        raise SecretStoreError("Gateway master key must decode to exactly 32 bytes")
    return key


class EncryptedFileSecretStore(AdapterSecretStore):
    """Persist individually authenticated secrets in one versioned JSON file."""

    def __init__(self, path: Path, master_key: str) -> None:
        self._path = path.resolve()
        self._key = decode_master_key(master_key)
        self._lock = asyncio.Lock()
        self._entries = self._load()
        for entry_key, entry in self._entries.items():
            self._decrypt(entry_key, entry)

    def _load(self) -> dict[str, dict[str, str]]:
        if not self._path.exists():
            return {}
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecretStoreError("encrypted secret file is corrupted") from exc
        if not isinstance(document, dict) or document.get("version") != FORMAT_VERSION:
            raise SecretStoreError("encrypted secret file version is unsupported")
        entries = document.get("entries")
        if not isinstance(entries, dict):
            raise SecretStoreError("encrypted secret file is corrupted")
        normalized: dict[str, dict[str, str]] = {}
        for key, value in entries.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise SecretStoreError("encrypted secret file is corrupted")
            if set(value) != {"nonce", "ciphertext", "tag"} or not all(
                isinstance(item, str) for item in value.values()
            ):
                raise SecretStoreError("encrypted secret file is corrupted")
            normalized[key] = dict(value)
        return normalized

    def _decrypt(self, key: str, value: dict[str, str]) -> str:
        try:
            nonce = base64.b64decode(value["nonce"], validate=True)
            ciphertext = base64.b64decode(value["ciphertext"], validate=True)
            tag = base64.b64decode(value["tag"], validate=True)
            cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
            cipher.update(key.encode())
            plaintext = cipher.decrypt_and_verify(ciphertext, tag)
            return plaintext.decode()
        except Exception as exc:
            raise SecretStoreError("encrypted secret authentication failed") from exc

    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        document: dict[str, Any] = {"version": FORMAT_VERSION, "entries": self._entries}
        try:
            temporary.write_text(
                json.dumps(document, separators=(",", ":")), encoding="utf-8"
            )
            temporary.replace(self._path)
        finally:
            if temporary.exists():
                temporary.unlink()

    async def get(self, key: str) -> str | None:
        async with self._lock:
            value = self._entries.get(key)
            return (
                None
                if value is None
                else await asyncio.to_thread(self._decrypt, key, value)
            )

    async def set(self, key: str, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError("secret value must be a non-empty string")
        async with self._lock:
            cipher = AES.new(self._key, AES.MODE_GCM)
            cipher.update(key.encode())
            ciphertext, tag = cipher.encrypt_and_digest(value.encode())
            self._entries[key] = {
                "nonce": base64.b64encode(cipher.nonce).decode(),
                "ciphertext": base64.b64encode(ciphertext).decode(),
                "tag": base64.b64encode(tag).decode(),
            }
            await asyncio.to_thread(self._write)
            if self._decrypt(key, self._entries[key]) != value:
                raise SecretStoreError("encrypted secret verification failed")

    async def delete(self, key: str) -> bool:
        async with self._lock:
            existed = self._entries.pop(key, None) is not None
            if existed:
                await asyncio.to_thread(self._write)
            return existed

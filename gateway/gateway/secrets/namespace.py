"""Adapter-isolated view over a host secret backend."""

from .interface import AdapterSecretStore


class NamespacedSecretStore(AdapterSecretStore):
    """Restrict secret access to one configured adapter instance."""

    def __init__(self, store: AdapterSecretStore, adapter_id: str) -> None:
        if not adapter_id or "/" in adapter_id or "\\" in adapter_id:
            raise ValueError("adapter secret namespace is invalid")
        self._store = store
        self._prefix = f"adapter/{adapter_id}/"

    def _key(self, key: str) -> str:
        if (
            not key
            or key.startswith(("/", "\\"))
            or ".." in key.split("/")
            or "\\" in key
        ):
            raise ValueError("adapter secret key is invalid")
        return f"{self._prefix}{key}"

    async def get(self, key: str) -> str | None:
        return await self._store.get(self._key(key))

    async def set(self, key: str, value: str) -> None:
        await self._store.set(self._key(key), value)

    async def delete(self, key: str) -> bool:
        return await self._store.delete(self._key(key))

"""Namespaced secret references for managed adapter configuration."""

from gateway.secrets import AdapterSecretStore


class ManagedSecretStore:
    """Store managed values in the existing encrypted backend under a safe namespace."""

    def __init__(self, store: AdapterSecretStore) -> None:
        self._store = store

    async def set(self, adapter_id: str, field: str, value: str) -> dict[str, str]:
        key = f"managed-adapter/{adapter_id}/{field}"
        await self._store.set(key, value)
        return {"managed": key}

    async def delete(self, adapter_id: str, field: str) -> None:
        await self._store.delete(f"managed-adapter/{adapter_id}/{field}")

    @staticmethod
    def public(config: object) -> object:
        """Replace managed references with non-sensitive configured markers."""
        if isinstance(config, dict):
            if set(config) == {"managed"}:
                return {"configured": True}
            return {key: ManagedSecretStore.public(value) for key, value in config.items()}
        if isinstance(config, list):
            return [ManagedSecretStore.public(value) for value in config]
        return config

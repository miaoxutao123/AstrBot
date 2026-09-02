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

    async def populate_cache(
        self, configs: list[dict[str, object]], cache: dict[str, str]
    ) -> None:
        """Load only referenced managed values into Host's in-memory resolver."""
        for config in configs:
            for reference in self.references(config):
                value = await self._store.get(reference)
                if value is not None:
                    cache[reference] = value

    @staticmethod
    def references(config: object) -> list[str]:
        if isinstance(config, dict):
            if set(config) == {"managed"} and isinstance(config["managed"], str):
                return [config["managed"]]
            return [
                reference
                for value in config.values()
                for reference in ManagedSecretStore.references(value)
            ]
        if isinstance(config, list):
            return [
                reference
                for value in config
                for reference in ManagedSecretStore.references(value)
            ]
        return []

    @staticmethod
    def runtime_config(config: object) -> object:
        """Convert opaque managed references to the existing resolver shape."""
        if isinstance(config, dict):
            if set(config) == {"managed"} and isinstance(config["managed"], str):
                return {"env": config["managed"]}
            return {
                key: ManagedSecretStore.runtime_config(value)
                for key, value in config.items()
            }
        if isinstance(config, list):
            return [ManagedSecretStore.runtime_config(value) for value in config]
        return config

    @staticmethod
    def public(config: object) -> object:
        """Replace managed references with non-sensitive configured markers."""
        if isinstance(config, dict):
            if set(config) == {"managed"}:
                return {"configured": True}
            return {
                key: ManagedSecretStore.public(value) for key, value in config.items()
            }
        if isinstance(config, list):
            return [ManagedSecretStore.public(value) for value in config]
        return config

"""Managed connection API contracts, including secret redaction."""

from fastapi.testclient import TestClient

from gateway.api import ApiKey, create_app
from gateway.control_plane import ManagedAdapterStore, ManagedSecretStore
from gateway.core import AdapterRegistry, AdapterRuntime, MemoryEventBus
from gateway.secrets import MemorySecretStore
from tests.fake_adapters import FakeIMAdapter


def test_managed_instance_crud_keeps_secret_out_of_public_data(tmp_path) -> None:  # type: ignore[no-untyped-def]
    bus = MemoryEventBus()
    adapters = AdapterRegistry()
    adapters.register_factory("qq_official", FakeIMAdapter)
    runtime = AdapterRuntime(adapters, bus)
    managed = ManagedAdapterStore(tmp_path / "managed.db")
    secrets = ManagedSecretStore(MemorySecretStore())
    app = create_app(
        runtime,
        bus,
        [ApiKey("admin", "secret", frozenset({"*"}))],
        managed_adapter_store=managed,
        managed_secret_store=secrets,
    )
    headers = {"Authorization": "Bearer secret"}
    with TestClient(app) as client:
        created = client.post(
            "/v1/adapter-instances",
            headers=headers,
            json={
                "id": "qq-main",
                "type": "qq_official",
                "enabled": False,
                "config": {"app_id": "123", "secret": "never-public"},
            },
        )
        listed = client.get("/v1/adapter-instances", headers=headers)
        patched = client.patch(
            "/v1/adapter-instances/qq-main",
            headers=headers,
            json={"config": {"app_id": "456"}},
        )
        deleted = client.delete("/v1/adapter-instances/qq-main", headers=headers)
        unavailable = client.post(
            "/v1/adapter-instances",
            headers=headers,
            json={"id": "unknown", "type": "not-installed", "enabled": False},
        )

    assert created.status_code == 200
    assert "never-public" not in str(created.json())
    assert listed.json()["instances"][0]["config"]["secret"] == {"configured": True}
    assert patched.json()["config"]["secret"] == {"configured": True}
    assert b"never-public" not in (tmp_path / "managed.db").read_bytes()
    assert deleted.status_code == 200
    assert unavailable.status_code == 400
    assert managed.list() == []


def test_adapter_type_catalog_is_host_owned(tmp_path) -> None:  # type: ignore[no-untyped-def]
    bus = MemoryEventBus()
    registry = AdapterRegistry()
    registry.register_factory("telegram", FakeIMAdapter)
    runtime = AdapterRuntime(registry, bus)
    app = create_app(
        runtime,
        bus,
        [ApiKey("reader", "secret", frozenset({"adapters:read"}))],
        managed_adapter_store=ManagedAdapterStore(tmp_path / "managed.db"),
    )
    with TestClient(app) as client:
        response = client.get(
            "/v1/adapter-types", headers={"Authorization": "Bearer secret"}
        )

    assert response.status_code == 200
    assert response.json()["adapter_types"] == [
        {
            "type": "telegram",
            "name": "Telegram",
            "family": "im",
            "auth_mode": "credentials",
            "fields": [
                {
                    "name": "token",
                    "label": "Bot token",
                    "type": "password",
                    "secret": True,
                    "required": True,
                }
            ],
        }
    ]

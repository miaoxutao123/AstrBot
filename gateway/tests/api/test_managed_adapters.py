"""Managed connection API contracts, including secret redaction."""

import asyncio

from fastapi.testclient import TestClient

from gateway.api import ApiKey, create_app
from gateway.control_plane import ManagedAdapterStore, ManagedSecretStore
from gateway.core import (
    GATEWAY_API_VERSION,
    AdapterAuthInfo,
    AdapterAuthStatus,
    AdapterDescriptor,
    AdapterRegistry,
    AdapterRuntime,
    AuthChallenge,
    MemoryEventBus,
)
from gateway.secrets import MemorySecretStore
from tests.fake_adapters import FakeIMAdapter


class FakeWeixinAdapter(FakeIMAdapter):
    """Exercise the generic QR API path without a real provider account."""

    DESCRIPTOR = AdapterDescriptor(
        adapter_type="weixin",
        name="Weixin OC",
        version="test",
        api_version=GATEWAY_API_VERSION,
        family="im",
    )

    def __init__(self, instance_id: str, config: object = None) -> None:
        super().__init__(instance_id, config if isinstance(config, dict) else None)
        self._waiting = False
        self._auth_reads = 0

    async def start_auth(self) -> AdapterAuthInfo:
        self._waiting = True
        self._auth_reads = 0
        return AdapterAuthInfo(
            AdapterAuthStatus.WAITING_USER,
            AuthChallenge(qr_uri="weixin://test-qr", instructions="Scan the code"),
        )

    async def auth_info(self) -> AdapterAuthInfo:
        self._auth_reads += 1
        if self._auth_reads > 1:
            self._waiting = False
        return AdapterAuthInfo(
            AdapterAuthStatus.WAITING_USER
            if self._waiting
            else AdapterAuthStatus.AUTHENTICATED,
            AuthChallenge(qr_uri="weixin://test-qr") if self._waiting else None,
        )


def test_managed_instance_crud_keeps_secret_out_of_public_data(tmp_path) -> None:  # type: ignore[no-untyped-def]
    bus = MemoryEventBus()
    adapters = AdapterRegistry()
    adapters.register_factory("qq_official", FakeIMAdapter)
    runtime = AdapterRuntime(adapters, bus)
    managed = ManagedAdapterStore(tmp_path / "managed.db")
    secret_store = MemorySecretStore()
    secrets = ManagedSecretStore(secret_store)
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
    assert asyncio.run(secret_store.get("managed-adapter/qq-main/secret")) is None
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
                    "label_key": "gateway.adapterFields.botToken",
                    "type": "password",
                    "secret": True,
                    "required": True,
                }
            ],
        }
    ]


def test_managed_weixin_create_and_qr_auth_api(tmp_path) -> None:  # type: ignore[no-untyped-def]
    bus = MemoryEventBus()
    registry = AdapterRegistry()
    registry.register_factory("weixin", FakeWeixinAdapter)
    app = create_app(
        AdapterRuntime(registry, bus),
        bus,
        [ApiKey("admin", "secret", frozenset({"*"}))],
        managed_adapter_store=ManagedAdapterStore(tmp_path / "managed.db"),
    )
    headers = {"Authorization": "Bearer secret"}
    with TestClient(app) as client:
        created = client.post(
            "/v1/adapter-instances",
            headers=headers,
            json={"id": "wx-main", "type": "weixin", "config": {}},
        )
        auth = client.post("/v1/adapters/wx-main/auth/start", headers=headers)
        waiting = client.get("/v1/adapters/wx-main/auth", headers=headers)
        authenticated = client.get("/v1/adapters/wx-main/auth", headers=headers)
    assert created.status_code == 200
    assert auth.json()["status"] == "waiting_user"
    assert auth.json()["challenge"]["qr_uri"] == "weixin://test-qr"
    assert waiting.json()["status"] == "waiting_user"
    assert authenticated.json()["status"] == "authenticated"

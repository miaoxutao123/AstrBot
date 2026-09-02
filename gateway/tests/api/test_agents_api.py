"""External Agent enrollment API integration coverage."""

from fastapi.testclient import TestClient

from gateway.api import ApiKey, create_app
from gateway.control_plane import AgentRegistry
from gateway.core import AdapterRegistry, AdapterRuntime, MemoryEventBus


def test_enrollment_register_heartbeat_and_revoke(tmp_path) -> None:  # type: ignore[no-untyped-def]
    bus = MemoryEventBus()
    registry = AgentRegistry(tmp_path / "agents.db")
    app = create_app(
        AdapterRuntime(AdapterRegistry(), bus),
        bus,
        [ApiKey("admin", "admin", frozenset({"*"}))],
        agent_registry=registry,
    )
    with TestClient(app) as client:
        admin = {"Authorization": "Bearer admin"}
        enrollment = client.post(
            "/v1/agent-enrollments",
            headers=admin,
            json={"name_hint": "echo", "scopes": ["adapters:read"], "ttl_seconds": 60},
        ).json()
        registered = client.post(
            "/v1/agents/register",
            json={
                "enrollment_token": enrollment["token"],
                "descriptor": {"display_name": "Echo Agent"},
            },
        ).json()
        heartbeat = client.post(
            "/v1/agents/me/heartbeat",
            headers={"Authorization": f"Bearer {registered['api_key']}"},
            json={"state": "ready"},
        )
        agent_headers = {"Authorization": f"Bearer {registered['api_key']}"}
        updated = client.patch(
            "/v1/agents/me",
            headers=agent_headers,
            json={"descriptor": {"display_name": "Echo Agent v2", "scopes": ["*"]}},
        )
        detail = client.get(f"/v1/agents/{registered['agent_id']}", headers=admin)
        agents = client.get("/v1/agents", headers=admin).json()["agents"]
        revoked = client.post(
            f"/v1/agents/{registered['agent_id']}/revoke", headers=admin
        )
        rejected = client.get(
            "/v1/discovery",
            headers={"Authorization": f"Bearer {registered['api_key']}"},
        )

    assert heartbeat.status_code == 200
    assert updated.json()["display_name"] == "Echo Agent v2"
    assert updated.json()["scopes"] == ["adapters:read"]
    assert detail.status_code == 200
    assert agents[0]["display_name"] == "Echo Agent v2"
    assert agents[0]["status"] == "ONLINE"
    assert revoked.status_code == 200
    assert rejected.status_code == 401

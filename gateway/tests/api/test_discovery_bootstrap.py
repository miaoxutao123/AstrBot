"""Discovery and bootstrap API contract tests."""

from fastapi.testclient import TestClient

from gateway.api import ApiKey, create_app
from gateway.control_plane import AgentRegistry
from gateway.core import AdapterRegistry, AdapterRuntime, MemoryEventBus
from tests.api.test_http_websocket import ADMIN_HEADERS, READ_HEADERS, build_im_app


def test_discovery_derives_authorized_bidirectional_endpoint() -> None:
    app, adapter = build_im_app()
    with TestClient(app) as client:
        assert client.portal is not None
        client.portal.call(adapter.emit_message, "private:1", "hello")
        response = client.get("/v1/discovery", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    endpoint = response.json()["endpoints"][0]
    assert endpoint["direction"] == "bidirectional"
    assert {item["name"] for item in endpoint["capabilities"]} >= {
        "im.message.receive",
        "im.message.send",
    }


def test_well_known_is_public_and_bootstrap_is_private() -> None:
    app, _ = build_im_app()
    with TestClient(app) as client:
        manifest = client.get("/.well-known/astrbot-gateway")
        guide = client.get("/docs/agent-bootstrap")
        denied = client.get("/v1/agent/bootstrap")
        bootstrap = client.get("/v1/agent/bootstrap", headers=READ_HEADERS)
    assert manifest.status_code == 200
    assert guide.status_code == 200
    assert "adapters" not in manifest.json()
    assert "secret" not in str(manifest.json()).lower()
    assert manifest.json()["authenticated_bootstrap"] == "/v1/agent/bootstrap"
    assert manifest.json()["agent_registration"]["endpoint"] == "/v1/agents/register"
    assert manifest.json()["profiles"]["im"]["default_event_filter"] == {
        "family": "im",
        "event_type": "im.message",
    }
    assert denied.status_code == 401
    assert bootstrap.status_code == 200
    assert bootstrap.json()["recommended_integration"]["bridge"] is True
    assert bootstrap.json()["gateway"]["events"] == "/v1/events/ws"
    assert bootstrap.json()["gateway"]["commands"] == "/v1/commands"
    assert bootstrap.json()["agent"]["heartbeat"] == "/v1/agents/me/heartbeat"
    assert bootstrap.json()["subscriptions"]["ordinary_im_messages"] == {
        "family": "im",
        "event_type": "im.message",
    }


def test_agent_can_follow_bootstrap_links_without_guessing_paths(tmp_path) -> None:  # type: ignore[no-untyped-def]
    bus = MemoryEventBus()
    app = create_app(
        AdapterRuntime(AdapterRegistry(), bus),
        bus,
        [ApiKey("admin", "admin-secret", frozenset({"*"}))],
        agent_registry=AgentRegistry(tmp_path / "agents.db"),
    )
    with TestClient(app) as client:
        manifest = client.get("/.well-known/astrbot-gateway").json()
        enrollment = client.post(
            "/v1/agent-enrollments",
            headers=ADMIN_HEADERS,
            json={"name_hint": "generic", "ttl_seconds": 60},
        ).json()
        registration = client.post(
            manifest["agent_registration"]["endpoint"],
            json={"enrollment_token": enrollment["token"], "descriptor": {}},
        ).json()
        bootstrap = client.get(
            registration["gateway"]["bootstrap"],
            headers={"Authorization": f"Bearer {registration['api_key']}"},
        )
    assert bootstrap.status_code == 200
    assert bootstrap.json()["gateway"]["events"] == registration["gateway"]["events"]
    assert bootstrap.json()["subscriptions"]["ordinary_im_messages"] == registration[
        "default_event_filter"
    ]

"""Discovery and bootstrap API contract tests."""

from fastapi.testclient import TestClient

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

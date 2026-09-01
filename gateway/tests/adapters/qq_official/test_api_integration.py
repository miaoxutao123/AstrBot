"""QQ Official event/WebSocket and HTTP/command closed loop."""

from fastapi.testclient import TestClient

from gateway.adapters.qq_official import QQOfficialWebSocketAdapter
from gateway.api import ApiKey, create_app
from gateway.core import AdapterRegistry, AdapterRuntime, MemoryEventBus
from tests.adapters.qq_official.fakes import FakeQQOfficialClient

HEADERS = {"Authorization": "Bearer test-secret"}


def test_qq_official_gateway_api_closed_loop() -> None:
    fake = FakeQQOfficialClient()
    registry = AdapterRegistry()
    registry.register(
        "qq-main",
        QQOfficialWebSocketAdapter(
            "qq-main",
            {"app_id": {"env": "APP"}, "secret": {"env": "SECRET"}},
            client_factory=lambda *_args: fake,
        ),
    )
    bus = MemoryEventBus()
    runtime = AdapterRuntime(
        registry,
        bus,
        secret_provider=lambda key: {"APP": "app", "SECRET": "secret"}.get(key),
    )
    app = create_app(
        runtime,
        bus,
        [ApiKey("test", "test-secret", frozenset({"events:read", "commands:send"}))],
    )
    with TestClient(app) as client:
        with client.websocket_connect("/v1/events/ws", headers=HEADERS) as socket:
            assert client.portal is not None
            client.portal.call(
                fake.emit,
                "GROUP_AT_MESSAGE_CREATE",
                {
                    "id": "group-message",
                    "group_openid": "group",
                    "author": {"member_openid": "member"},
                    "content": "hello",
                },
            )
            envelope = socket.receive_json()
        response = client.post(
            "/v1/commands",
            headers=HEADERS,
            json={
                "id": "qq-send",
                "target": envelope["data"]["source"],
                "type": "im.message.reply",
                "payload": {
                    "schema": "im.message.outbound.v1",
                    "data": {
                        "reply_to": "group-message",
                        "segments": [{"type": "text", "data": {"text": "reply"}}],
                    },
                },
            },
        )
    assert envelope["data"]["source"] == {
        "family": "im",
        "adapter_type": "qq_official",
        "adapter_id": "qq-main",
        "endpoint_id": "group:group",
    }
    assert response.status_code == 200 and response.json()["status"] == "success"
    assert fake.calls[0][1] == "/v2/groups/group/messages"
    assert fake.stopped

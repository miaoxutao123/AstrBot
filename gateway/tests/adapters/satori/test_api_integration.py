"""Satori event-to-WebSocket and HTTP-command closed loop."""

from fastapi.testclient import TestClient

from gateway.adapters.satori import SatoriAdapter
from gateway.adapters.satori.protocol import EVENT
from gateway.api import ApiKey, create_app
from gateway.core import AdapterRegistry, AdapterRuntime, MemoryEventBus
from tests.adapters.satori.fakes import FakeSatoriClient

HEADERS = {"Authorization": "Bearer test-secret"}


def test_satori_gateway_api_closed_loop() -> None:
    fake = FakeSatoriClient()
    registry = AdapterRegistry()
    registry.register(
        "satori-main",
        SatoriAdapter(
            "satori-main",
            client_factory=lambda _config, _token, _sequence: fake,
        ),
    )
    bus = MemoryEventBus()
    runtime = AdapterRuntime(registry, bus)
    app = create_app(
        runtime,
        bus,
        [ApiKey("test", "test-secret", frozenset({"events:read", "commands:send"}))],
    )

    with TestClient(app) as client:
        with client.websocket_connect("/v1/events/ws", headers=HEADERS) as websocket:
            assert client.portal is not None
            client.portal.call(
                fake.emit,
                {
                    "op": EVENT,
                    "body": {
                        "type": "message-created",
                        "login": {"platform": "discord", "user": {"id": "bot"}},
                        "user": {"id": "member", "name": "Member"},
                        "channel": {"id": "channel"},
                        "message": {"id": "m1", "content": "hello"},
                    },
                },
            )
            envelope = websocket.receive_json()
        endpoint = envelope["data"]["source"]
        response = client.post(
            "/v1/commands",
            headers=HEADERS,
            json={
                "id": "send-satori",
                "target": endpoint,
                "type": "im.message.send",
                "payload": {
                    "schema": "im.message.outbound.v1",
                    "data": {"segments": [{"type": "text", "data": {"text": "reply"}}]},
                },
            },
        )

    assert envelope["data"]["source"]["adapter_type"] == "satori"
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert fake.calls[0][1] == "/message.create"
    assert fake.stopped

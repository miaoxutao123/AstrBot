"""OneBot AdapterRuntime and API closed-loop integration tests."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.adapters.onebot import OneBotAdapter
from gateway.api import ApiKey, create_app
from gateway.core import AdapterRegistry, AdapterRuntime, AdapterState, MemoryEventBus
from gateway.profiles.im import IM_MESSAGE_DELETE, IM_MESSAGE_REPLY, IM_MESSAGE_SEND
from tests.adapters.onebot.fakes import FakeOneBotClient

FIXTURES = Path(__file__).parents[2] / "fixtures" / "onebot"
HEADERS = {"Authorization": "Bearer test-secret"}


def load_private_event() -> dict[str, Any]:
    """Load the private message fixture.

    Returns:
        Parsed OneBot payload.
    """
    loaded = json.loads((FIXTURES / "private_text.json").read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError("OneBot fixture must be an object")
    return dict(loaded)


def build_app(
    fake: FakeOneBotClient,
) -> tuple[FastAPI, AdapterRuntime]:
    """Build an API around an injected OneBot client.

    Args:
        fake: Deterministic transport client.

    Returns:
        ASGI application and adapter runtime.
    """
    event_bus = MemoryEventBus()
    registry = AdapterRegistry()
    adapter = OneBotAdapter(
        "qq-main",
        {
            "mode": "websocket",
            "endpoint": "ws://127.0.0.1:3001",
            "token": {"env": "ONEBOT_TOKEN"},
        },
        client_factory=lambda _config, token: fake,
    )
    registry.register("qq-main", adapter)
    runtime = AdapterRuntime(
        registry,
        event_bus,
        secret_provider=lambda key: "valid-token" if key == "ONEBOT_TOKEN" else None,
    )
    app = create_app(
        runtime,
        event_bus,
        [
            ApiKey(
                "test",
                "test-secret",
                frozenset(
                    {
                        "events:read",
                        "commands:send",
                        "adapters:read",
                        "media:read",
                        "media:write",
                    }
                ),
            )
        ],
    )
    return app, runtime


def test_onebot_event_websocket_http_command_reconnect_and_shutdown() -> None:
    fake = FakeOneBotClient()
    app, runtime = build_app(fake)

    with TestClient(app) as client:
        assert runtime.info("qq-main").state == AdapterState.RUNNING
        with client.websocket_connect("/v1/events/ws", headers=HEADERS) as websocket:
            assert client.portal is not None
            client.portal.call(fake.emit, load_private_event())
            envelope = websocket.receive_json()
            response = client.post(
                "/v1/commands",
                headers=HEADERS,
                json={
                    "id": "cmd_onebot",
                    "target": {
                        "transport": "im",
                        "adapter_id": "qq-main",
                        "endpoint_id": "private:20001",
                    },
                    "type": IM_MESSAGE_SEND,
                    "payload": {
                        "schema": "im.message.outbound.v1",
                        "data": {
                            "segments": [{"type": "text", "data": {"text": "reply"}}]
                        },
                    },
                },
            )
        fake.disconnect()
        assert runtime.info("qq-main").state == AdapterState.DEGRADED
        fake.reconnect()
        assert runtime.info("qq-main").state == AdapterState.RUNNING

    assert fake.stopped
    assert envelope["type"] == "event"
    assert envelope["data"]["payload"]["schema"] == "im.message.v1"
    assert response.status_code == 200
    assert response.json()["external_id"] == "9001"
    action, params = fake.actions[-1]
    assert action == "send_private_msg"
    assert params["user_id"] == 20001
    assert params["message"][0]["data"]["text"] == "reply"
    assert params["self_id"] == 10000


def test_invalid_token_state_and_unsupported_command() -> None:
    fake = FakeOneBotClient(AdapterState.FAILED)
    app, runtime = build_app(fake)

    with TestClient(app) as client:
        assert runtime.info("qq-main").state == AdapterState.FAILED
        response = client.post(
            "/v1/commands",
            headers=HEADERS,
            json={
                "id": "cmd_unknown",
                "target": {
                    "transport": "im",
                    "adapter_id": "qq-main",
                    "endpoint_id": "private:20001",
                },
                "type": "onebot.unsupported",
                "payload": {"schema": "onebot.unknown.v1", "data": {}},
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"]["code"] == "ADAPTER_OFFLINE"


def test_unsupported_command_is_explicit_when_connected() -> None:
    app, _runtime = build_app(FakeOneBotClient())

    with TestClient(app) as client:
        response = client.post(
            "/v1/commands",
            headers=HEADERS,
            json={
                "id": "cmd_unknown",
                "target": {
                    "transport": "im",
                    "adapter_id": "qq-main",
                    "endpoint_id": "private:20001",
                },
                "type": "onebot.unsupported",
                "payload": {"schema": "onebot.unknown.v1", "data": {}},
            },
        )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"


def test_http_reply_with_image_and_file_uses_standard_profile() -> None:
    fake = FakeOneBotClient()
    app, _runtime = build_app(fake)

    with TestClient(app) as client:
        image = client.post(
            "/v1/media",
            headers=HEADERS,
            files={"upload": ("photo.jpg", b"image", "image/jpeg")},
        ).json()["media"]
        file = client.post(
            "/v1/media",
            headers=HEADERS,
            files={"upload": ("report.txt", b"file", "text/plain")},
        ).json()["media"]
        response = client.post(
            "/v1/commands",
            headers=HEADERS,
            json={
                "id": "cmd_media_reply",
                "target": {
                    "transport": "im",
                    "adapter_id": "qq-main",
                    "endpoint_id": "group:30001:user:20002",
                },
                "type": IM_MESSAGE_REPLY,
                "payload": {
                    "schema": "im.message.outbound.v1",
                    "data": {
                        "reply_to": "102",
                        "segments": [
                            {"type": "image", "data": {"media": image}},
                            {"type": "file", "data": {"media": file}},
                        ],
                    },
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    action, params = fake.actions[-1]
    assert action == "send_group_msg"
    assert params["group_id"] == 30001
    assert [segment["type"] for segment in params["message"]] == [
        "reply",
        "image",
        "file",
    ]


def test_http_delete_uses_onebot_delete_action() -> None:
    fake = FakeOneBotClient()
    app, _runtime = build_app(fake)

    with TestClient(app) as client:
        response = client.post(
            "/v1/commands",
            headers=HEADERS,
            json={
                "id": "cmd_delete",
                "target": {
                    "transport": "im",
                    "adapter_id": "qq-main",
                    "endpoint_id": "private:20001",
                },
                "type": IM_MESSAGE_DELETE,
                "payload": {
                    "schema": "im.message.delete.v1",
                    "data": {"message_id": "102"},
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    action, params = fake.actions[-1]
    assert action == "delete_msg"
    assert params["message_id"] == 102

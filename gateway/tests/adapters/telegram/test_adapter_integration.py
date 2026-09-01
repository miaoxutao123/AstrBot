"""Telegram AdapterRuntime and API closed-loop integration tests."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.adapters.telegram import TelegramAdapter
from gateway.api import ApiKey, create_app
from gateway.core import AdapterRegistry, AdapterRuntime, AdapterState, MemoryEventBus
from gateway.profiles.im import (
    IM_MESSAGE_DELETE,
    IM_MESSAGE_EDIT,
    IM_MESSAGE_SEND,
    IM_REACTION_ADD,
    IM_REACTION_REMOVE,
    IM_TYPING_SET,
)
from tests.adapters.telegram.fakes import FakeTelegramClient

FIXTURES = Path(__file__).parents[2] / "fixtures" / "telegram"
HEADERS = {"Authorization": "Bearer test-secret"}


def private_update() -> dict[str, Any]:
    loaded = json.loads((FIXTURES / "private_text.json").read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError("Telegram fixture must be an object")
    return dict(loaded)


def build_app(fake: FakeTelegramClient) -> tuple[FastAPI, AdapterRuntime]:
    event_bus = MemoryEventBus()
    registry = AdapterRegistry()
    adapter = TelegramAdapter(
        "telegram-main",
        {
            "token": {"env": "TELEGRAM_TOKEN"},
            "media_group_timeout": 0.01,
            "media_group_max_wait": 0.1,
        },
        client_factory=lambda _config, _token: fake,
    )
    registry.register("telegram-main", adapter)
    runtime = AdapterRuntime(
        registry,
        event_bus,
        secret_provider=lambda key: "123:token" if key == "TELEGRAM_TOKEN" else None,
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


def command(
    command_id: str,
    command_type: str,
    schema: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": command_id,
        "target": {
            "family": "im",
            "adapter_type": "telegram",
            "adapter_id": "telegram-main",
            "endpoint_id": "group:-100123",
        },
        "type": command_type,
        "payload": {"schema": schema, "data": data},
    }


def test_telegram_event_commands_reconnect_and_shutdown() -> None:
    fake = FakeTelegramClient()
    app, runtime = build_app(fake)

    with TestClient(app) as client:
        assert runtime.info("telegram-main").state == AdapterState.RUNNING
        with client.websocket_connect("/v1/events/ws", headers=HEADERS) as websocket:
            assert client.portal is not None
            client.portal.call(fake.emit, private_update())
            envelope = websocket.receive_json()
        sent = client.post(
            "/v1/commands",
            headers=HEADERS,
            json=command(
                "send",
                IM_MESSAGE_SEND,
                "im.message.outbound.v1",
                {"segments": [{"type": "text", "data": {"text": "hello"}}]},
            ),
        )
        edited = client.post(
            "/v1/commands",
            headers=HEADERS,
            json=command(
                "edit",
                IM_MESSAGE_EDIT,
                "im.message.edit.v1",
                {
                    "message_id": "701",
                    "segments": [{"type": "text", "data": {"text": "edited"}}],
                },
            ),
        )
        reacted = client.post(
            "/v1/commands",
            headers=HEADERS,
            json=command(
                "reaction-add",
                IM_REACTION_ADD,
                "im.reaction.v1",
                {"message_id": "701", "emoji": "👍", "big": True},
            ),
        )
        removed = client.post(
            "/v1/commands",
            headers=HEADERS,
            json=command(
                "reaction-remove",
                IM_REACTION_REMOVE,
                "im.reaction.v1",
                {"message_id": "701"},
            ),
        )
        typing = client.post(
            "/v1/commands",
            headers=HEADERS,
            json=command(
                "typing",
                IM_TYPING_SET,
                "im.typing.v1",
                {"action": "typing"},
            ),
        )
        deleted = client.post(
            "/v1/commands",
            headers=HEADERS,
            json=command(
                "delete",
                IM_MESSAGE_DELETE,
                "im.message.delete.v1",
                {"message_id": "701"},
            ),
        )
        fake.disconnect()
        assert runtime.info("telegram-main").state == AdapterState.DEGRADED
        fake.reconnect()
        assert runtime.info("telegram-main").state == AdapterState.RUNNING

    assert fake.stopped
    assert envelope["data"]["payload"]["schema"] == "im.message.v1"
    assert all(
        response.json()["status"] == "success"
        for response in (sent, edited, reacted, removed, typing, deleted)
    )
    assert [method for method, _params in fake.calls] == [
        "send_message",
        "edit_message_text",
        "set_message_reaction",
        "set_message_reaction",
        "send_chat_action",
        "delete_message",
    ]


def test_media_group_is_one_event_and_media_send_uses_api() -> None:
    fake = FakeTelegramClient()
    app, _runtime = build_app(fake)
    first = private_update()
    first["message"].pop("text")
    first["message"].pop("entities")
    first["message"].update(
        {"media_group_id": "album-1", "photo": [{"file_id": "photo-file"}]}
    )
    second = private_update()
    second["update_id"] = 1003
    second["message"]["message_id"] = 53
    second["message"].pop("text")
    second["message"].pop("entities")
    second["message"].update(
        {
            "media_group_id": "album-1",
            "document": {
                "file_id": "document-file",
                "file_name": "report.txt",
                "mime_type": "text/plain",
            },
        }
    )

    with TestClient(app) as client:
        with client.websocket_connect("/v1/events/ws", headers=HEADERS) as websocket:
            assert client.portal is not None
            client.portal.call(fake.emit, first)
            client.portal.call(fake.emit, second)
            envelope = websocket.receive_json()
        uploaded = client.post(
            "/v1/media",
            headers=HEADERS,
            files={"upload": ("send.txt", b"content", "text/plain")},
        ).json()["media"]
        response = client.post(
            "/v1/commands",
            headers=HEADERS,
            json=command(
                "send-file",
                IM_MESSAGE_SEND,
                "im.message.outbound.v1",
                {"segments": [{"type": "file", "data": {"media": uploaded}}]},
            ),
        )

    assert envelope["data"]["metadata"]["media_group_count"] == 2
    assert [
        segment["type"] for segment in envelope["data"]["payload"]["data"]["segments"]
    ] == ["image", "file"]
    assert response.json()["status"] == "success"
    assert fake.calls[-1][0] == "send_document"


def test_invalid_token_and_unsupported_command_are_explicit() -> None:
    failed_app, failed_runtime = build_app(FakeTelegramClient(AdapterState.FAILED))
    with TestClient(failed_app):
        assert failed_runtime.info("telegram-main").state == AdapterState.FAILED

    app, _runtime = build_app(FakeTelegramClient())
    with TestClient(app) as client:
        response = client.post(
            "/v1/commands",
            headers=HEADERS,
            json=command("unsupported", "telegram.admin", "telegram.admin.v1", {}),
        )

    assert response.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"

"""Phase 2 REST, authorization, and WebSocket integration tests."""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from gateway.api import ApiKey, create_app
from gateway.core import (
    AdapterRegistry,
    AdapterRuntime,
    CommandResult,
    EndpointRef,
    GatewayCommand,
    GatewayEvent,
    MemoryEventBus,
)
from gateway.profiles.im import IMConversation, IMMessage, IMSegment, IMSender
from tests.fake_adapters import FakeIMAdapter, FakeRobotAdapter

READ_HEADERS = {"Authorization": "Bearer read-secret"}
COMMAND_HEADERS = {"Authorization": "Bearer command-secret"}
ADMIN_HEADERS = {"Authorization": "Bearer admin-secret"}


class LoopbackIMAdapter(FakeIMAdapter):
    """Emit an inbound event after every successful test command."""

    async def execute(self, command: GatewayCommand) -> CommandResult:
        """Record a command and emit a correlated fake reply.

        Args:
            command: Command submitted through HTTP.

        Returns:
            Successful fake command result.
        """
        result = await super().execute(command)
        assert self.context is not None
        await self.context.emit(
            GatewayEvent(
                id=f"evt_{command.id}",
                source=EndpointRef(
                    "im",
                    "fake-im",
                    self.instance_id,
                    command.target.endpoint_id,
                ),
                type="im.message",
                payload=IMMessage(
                    message_id=result.external_id or "fake-missing-id",
                    conversation=IMConversation("private", command.target.endpoint_id),
                    sender=IMSender(command.target.endpoint_id, "Loopback User"),
                    segments=(IMSegment.text("ack"),),
                ).to_payload(),
                correlation_id=command.id,
            )
        )
        return result


def build_im_app(
    heartbeat_interval: float = 1.0,
) -> tuple[FastAPI, LoopbackIMAdapter]:
    """Build an API application with one loopback IM adapter.

    Args:
        heartbeat_interval: WebSocket heartbeat interval.

    Returns:
        FastAPI application and configured fake adapter.
    """
    event_bus = MemoryEventBus()
    registry = AdapterRegistry()
    adapter = LoopbackIMAdapter()
    registry.register(adapter.instance_id, adapter)
    runtime = AdapterRuntime(registry, event_bus)
    app = create_app(
        runtime,
        event_bus,
        [
            ApiKey(
                "reader", "read-secret", frozenset({"events:read", "adapters:read"})
            ),
            ApiKey(
                "commander",
                "command-secret",
                frozenset({"events:read", "adapters:read", "commands:send"}),
            ),
            ApiKey("admin", "admin-secret", frozenset({"*"})),
        ],
        heartbeat_interval=heartbeat_interval,
    )
    return app, adapter


def command_body(command_id: str) -> dict[str, Any]:
    """Build a valid IM command request.

    Args:
        command_id: Stable command ID.

    Returns:
        JSON-compatible request body.
    """
    return {
        "id": command_id,
        "target": {
            "family": "im",
            "adapter_type": "fake-im",
            "adapter_id": "im-main",
            "endpoint_id": "user:1",
        },
        "type": "im.message.send",
        "payload": {
            "schema": "im.message.outbound.v1",
            "data": {"segments": [{"type": "text", "data": {"text": "hello"}}]},
        },
    }


def test_health_authentication_and_adapter_controls() -> None:
    app, _adapter = build_im_app()

    with TestClient(app) as client:
        health = client.get("/v1/health")
        missing_key = client.get("/v1/adapters")
        wrong_scope = client.post(
            "/v1/adapters/im-main/stop",
            headers=READ_HEADERS,
        )
        adapter = client.get("/v1/adapters/im-main", headers=READ_HEADERS)
        stopped = client.post(
            "/v1/adapters/im-main/stop",
            headers=ADMIN_HEADERS,
        )
        restarted = client.post(
            "/v1/adapters/im-main/restart",
            headers=ADMIN_HEADERS,
        )

    assert health.status_code == 200
    assert health.json()["event_bus"] == "running"
    assert missing_key.status_code == 401
    assert missing_key.json()["error"]["code"] == "AUTH_FAILED"
    assert wrong_scope.status_code == 403
    assert adapter.json()["id"] == "im-main"
    assert adapter.json()["type"] == "fake-im"
    assert adapter.json()["family"] == "im"
    assert adapter.json()["state"] == "running"
    assert stopped.json()["state"] == "stopped"
    assert restarted.json()["state"] == "running"


def test_http_command_to_websocket_event_complete_loop() -> None:
    app, adapter = build_im_app()

    with TestClient(app) as client:
        with client.websocket_connect(
            "/v1/events/ws",
            headers=COMMAND_HEADERS,
        ) as websocket:
            assert client.portal is not None
            emitted = client.portal.call(
                adapter.emit_message,
                "user:1",
                "hello from transport",
                "message-in",
            )
            envelope = websocket.receive_json()
            response = client.post(
                "/v1/commands",
                headers=COMMAND_HEADERS,
                json=command_body("cmd_loop"),
            )

        event_id = envelope["data"]["id"]
        retained = client.get(f"/v1/events/{event_id}", headers=READ_HEADERS)
        endpoints = client.get("/v1/endpoints", headers=READ_HEADERS)
        endpoint_id = endpoints.json()["endpoints"][0]["id"]
        capabilities = client.get(
            f"/v1/endpoints/{endpoint_id}/capabilities",
            headers=READ_HEADERS,
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert adapter.commands[0].id == "cmd_loop"
    assert envelope["type"] == "event"
    assert envelope["data"]["id"] == emitted.id
    assert envelope["data"]["payload"]["data"]["message_id"] == "message-in"
    assert retained.status_code == 200
    assert capabilities.status_code == 200
    assert {item["name"] for item in capabilities.json()["capabilities"]} >= {
        "im.message.send",
        "im.message.reply",
    }


def test_websocket_reconnect_heartbeat_and_cleanup() -> None:
    app, _adapter = build_im_app(heartbeat_interval=0.02)

    with TestClient(app) as client:
        first = client.post(
            "/v1/commands",
            headers=COMMAND_HEADERS,
            json=command_body("cmd_first"),
        )
        second = client.post(
            "/v1/commands",
            headers=COMMAND_HEADERS,
            json=command_body("cmd_second"),
        )
        assert first.status_code == second.status_code == 200

        with client.websocket_connect(
            "/v1/events/ws?last_event_id=evt_cmd_first",
            headers=READ_HEADERS,
        ) as websocket:
            replay = websocket.receive_json()
            heartbeat = websocket.receive_json()

        services = app.state.gateway_services
        assert services.events.subscription_count == 0

    assert replay["type"] == "event"
    assert replay["data"]["id"] == "evt_cmd_second"
    assert heartbeat["type"] == "heartbeat"
    assert heartbeat["data"]["cursor"] == "evt_cmd_second"


def test_invalid_request_and_missing_event_use_stable_errors() -> None:
    app, _adapter = build_im_app()

    with TestClient(app) as client:
        invalid = client.post(
            "/v1/commands",
            headers=COMMAND_HEADERS,
            json={"type": "im.message.send"},
        )
        missing = client.get("/v1/events/missing", headers=READ_HEADERS)

    assert invalid.status_code == 422
    assert invalid.json() == {
        "error": {
            "code": "INVALID_COMMAND",
            "message": "request validation failed",
            "retryable": False,
            "details": {},
        }
    }
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "EVENT_NOT_FOUND"


def test_websocket_rejects_missing_api_key() -> None:
    app, _adapter = build_im_app()

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/v1/events/ws"):
                pass

    assert exc_info.value.code == 4401


def test_unexpected_error_is_sanitized() -> None:
    app, _adapter = build_im_app()

    @app.get("/test/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("sensitive implementation detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test/unexpected")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "internal server error",
            "retryable": False,
            "details": {},
        }
    }
    assert "sensitive" not in response.text


def test_hardware_command_requires_hardware_scope() -> None:
    event_bus = MemoryEventBus()
    registry = AdapterRegistry()
    robot = FakeRobotAdapter()
    registry.register(robot.instance_id, robot)
    runtime = AdapterRuntime(registry, event_bus)
    app = create_app(
        runtime,
        event_bus,
        [
            ApiKey("command", "command-secret", frozenset({"commands:send"})),
            ApiKey(
                "hardware",
                "hardware-secret",
                frozenset({"commands:send", "hardware:control"}),
            ),
        ],
    )
    body = {
        "id": "cmd_robot",
        "target": {
            "family": "robot",
            "adapter_type": "fake-robot",
            "adapter_id": robot.instance_id,
            "endpoint_id": "/base",
        },
        "type": "robot.stop",
        "payload": {"schema": "robot.stop.v1", "data": {}},
    }

    with TestClient(app) as client:
        forbidden = client.post(
            "/v1/commands",
            headers=COMMAND_HEADERS,
            json=body,
        )
        allowed = client.post(
            "/v1/commands",
            headers={"Authorization": "Bearer hardware-secret"},
            json=body,
        )

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "success"


def test_generic_auth_routes_report_not_required() -> None:
    app, _adapter = build_im_app()

    with TestClient(app) as client:
        current = client.get("/v1/adapters/im-main/auth", headers=READ_HEADERS)
        started = client.post("/v1/adapters/im-main/auth/start", headers=ADMIN_HEADERS)
        cancelled = client.post(
            "/v1/adapters/im-main/auth/cancel", headers=ADMIN_HEADERS
        )

    assert current.status_code == 200
    assert started.status_code == 200
    assert cancelled.status_code == 200
    assert current.json() == {"status": "not_required"}
    assert started.json() == {"status": "not_required"}
    assert cancelled.json() == {"status": "not_required"}

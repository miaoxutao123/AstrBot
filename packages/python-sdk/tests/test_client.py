"""SDK wire-protocol tests without importing Gateway implementation modules."""

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import httpx
import pytest

import astrbot_gateway_sdk.client as client_module
from astrbot_gateway_sdk import AsyncGatewayClient
from astrbot_gateway_sdk import GatewayWebSocketAuthenticationError


def endpoint() -> dict[str, str]:
    return {
        "family": "im",
        "adapter_type": "fake-im",
        "adapter_id": "im-main",
        "endpoint_id": "user:1",
    }


def event(event_id: str = "evt-1") -> dict[str, Any]:
    return {
        "id": event_id,
        "type": "im.message",
        "source": endpoint(),
        "payload": {
            "schema": "im.message.v1",
            "data": {
                "message_id": "message-1",
                "sender": {"id": "user:1"},
                "segments": [{"type": "text", "data": {"text": "hello"}}],
            },
        },
        "metadata": {"transport": "fake"},
        "correlation_id": None,
    }


class FakeSocket:
    def __init__(self, values: list[dict[str, Any]]) -> None:
        self.values = values

    async def __aenter__(self) -> "FakeSocket":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def __aiter__(self) -> "FakeSocket":
        return self

    async def __anext__(self) -> str:
        if not self.values:
            raise ConnectionError("test disconnect")
        return json.dumps(self.values.pop(0))


async def test_http_auth_media_and_reply_helper() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/adapters":
            return httpx.Response(200, json={"adapters": [{"id": "im-main"}]})
        if request.url.path == "/v1/endpoints":
            return httpx.Response(
                200, json={"endpoints": [{"id": "endpoint-1", "endpoint": endpoint()}]}
            )
        if request.url.path == "/v1/endpoints/endpoint-1/capabilities":
            return httpx.Response(
                200, json={"capabilities": [{"name": "im.message.reply"}]}
            )
        if request.url.path == "/v1/media":
            return httpx.Response(200, json={"media": {"media_id": "media-1"}})
        if request.url.path == "/v1/commands":
            return httpx.Response(200, json={"status": "success", "command_id": "cmd"})
        return httpx.Response(404)

    async with AsyncGatewayClient(
        "http://gateway.invalid",
        api_key="secret",
        client=httpx.AsyncClient(
            base_url="http://gateway.invalid", transport=httpx.MockTransport(handler)
        ),
    ) as gateway:
        assert (await gateway.health())["status"] == "ok"
        assert (await gateway.list_adapters())[0]["id"] == "im-main"
        endpoints = await gateway.list_endpoints()
        assert (await gateway.get_capabilities(endpoints[0]))[0]["name"] == "im.message.reply"
        uploaded = await gateway.upload_media(b"bytes", filename="hello.txt", mime_type="text/plain")
        reply = await gateway.reply(client_module.GatewayEvent.from_wire(event()), "answer")

    assert uploaded["media_id"] == "media-1"
    assert reply["status"] == "success"
    assert all(request.headers["authorization"] == "Bearer secret" for request in requests)
    command = json.loads(requests[-1].content)
    assert command["type"] == "im.message.reply"
    assert command["payload"]["data"]["reply_to"] == "message-1"
    assert command["payload"]["data"]["segments"] == [
        {"type": "text", "data": {"text": "answer"}}
    ]
    assert command["correlation_id"] == "evt-1"


async def test_events_reconnect_with_replay_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    sockets = [
        FakeSocket([{"type": "event", "data": event("evt-1")}]),
        FakeSocket([{"type": "event", "data": event("evt-2")}]),
    ]
    urls: list[str] = []

    def fake_connect(url: str, **_kwargs: object) -> FakeSocket:
        urls.append(url)
        return sockets.pop(0)

    monkeypatch.setattr(client_module, "connect", fake_connect)
    gateway = AsyncGatewayClient("http://gateway.invalid", api_key="secret", reconnect_delay=0)
    stream = gateway.events(family="im", event_type="im.message")
    first = await anext(stream)
    second = await anext(stream)
    await stream.aclose()
    await gateway.aclose()

    assert first.message is not None and first.message.text == "hello"
    assert second.id == "evt-2"
    assert "last_event_id=evt-1" in urls[1]
    assert "family=im" in urls[0] and "event_type=im.message" in urls[0]


class Close:
    def __init__(self, code: int) -> None:
        self.code = code


class WebSocketFailure(Exception):
    def __init__(self, code: int) -> None:
        self.rcvd = Close(code)


class RejectingSocket:
    def __init__(self, code: int) -> None:
        self.code = code

    async def __aenter__(self) -> "RejectingSocket":
        raise WebSocketFailure(self.code)

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.mark.parametrize("code", [4401, 4403])
async def test_events_authentication_close_does_not_reconnect(
    code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0

    def fake_connect(_url: str, **_kwargs: object) -> RejectingSocket:
        nonlocal attempts
        attempts += 1
        return RejectingSocket(code)

    monkeypatch.setattr(client_module, "connect", fake_connect)
    gateway = AsyncGatewayClient("http://gateway.invalid", reconnect_delay=0)
    with pytest.raises(GatewayWebSocketAuthenticationError, match=str(code)):
        await anext(gateway.events())
    await gateway.aclose()
    assert attempts == 1


def test_sdk_has_no_gateway_implementation_imports() -> None:
    source = (client_module.__file__ and open(client_module.__file__, encoding="utf-8").read())
    assert source is not None
    assert "gateway.core" not in source
    assert "gateway.adapters" not in source

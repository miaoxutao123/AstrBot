"""Real loopback protocol tests for the forward OneBot WebSocket client."""

import asyncio
from typing import Any

import pytest
from aiohttp import web

from gateway.adapters.onebot.client import ForwardWebSocketClient
from gateway.adapters.onebot.config import OneBotConfig
from gateway.core import AdapterState


async def start_server(
    handler: Any,
) -> tuple[web.AppRunner, str]:
    """Start an ephemeral loopback aiohttp server.

    Args:
        handler: aiohttp request handler.

    Returns:
        App runner and WebSocket URL.
    """
    application = web.Application()
    application.router.add_get("/onebot", handler)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    server = site._server
    sockets: Any = getattr(server, "sockets", None)
    assert sockets
    port = sockets[0].getsockname()[1]
    return runner, f"ws://127.0.0.1:{port}/onebot"


@pytest.mark.asyncio
async def test_forward_client_event_action_disconnect_reconnect_and_shutdown() -> None:
    connection_count = 0
    second_connection = asyncio.Event()
    reconnected = asyncio.Event()
    received_events: list[dict[str, Any]] = []
    states: list[AdapterState] = []

    async def onebot(request: web.Request) -> web.WebSocketResponse:
        nonlocal connection_count
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        connection_count += 1
        if connection_count == 1:
            await websocket.send_json(
                {
                    "post_type": "message",
                    "message_type": "private",
                    "message_id": 1,
                    "user_id": 2,
                    "sender": {"user_id": 2, "nickname": "test"},
                    "message": [{"type": "text", "data": {"text": "hello"}}],
                }
            )
            await websocket.close()
            return websocket
        second_connection.set()
        async for message in websocket:
            payload = message.json()
            await websocket.send_json(
                {
                    "status": "ok",
                    "retcode": 0,
                    "data": {"message_id": 42},
                    "echo": payload["echo"],
                }
            )
        return websocket

    runner, endpoint = await start_server(onebot)
    client = ForwardWebSocketClient(
        OneBotConfig.from_mapping(
            {
                "mode": "websocket",
                "endpoint": endpoint,
                "reconnect_max_delay": 0.05,
            }
        ),
        None,
    )

    async def on_event(event: Any) -> None:
        received_events.append(dict(event))

    def report(state: AdapterState, _reason: str | None) -> None:
        states.append(state)
        if state == AdapterState.RUNNING and states.count(AdapterState.RUNNING) >= 2:
            reconnected.set()

    try:
        await client.start(
            on_event,
            report,
        )
        await asyncio.wait_for(second_connection.wait(), timeout=2)
        await asyncio.wait_for(reconnected.wait(), timeout=2)
        result = await client.call_action("send_private_msg", user_id=2, message=[])
    finally:
        await client.stop()
        await runner.cleanup()

    assert received_events[0]["message_id"] == 1
    assert result["message_id"] == 42
    assert states.count(AdapterState.RUNNING) >= 2
    assert AdapterState.DEGRADED in states


@pytest.mark.asyncio
async def test_forward_client_reports_invalid_token_as_failed() -> None:
    failed = asyncio.Event()
    states: list[AdapterState] = []

    async def reject(_request: web.Request) -> web.Response:
        return web.Response(status=401)

    runner, endpoint = await start_server(reject)
    client = ForwardWebSocketClient(
        OneBotConfig.from_mapping({"mode": "websocket", "endpoint": endpoint}),
        "invalid-token",
    )

    def report(state: AdapterState, _reason: str | None) -> None:
        states.append(state)
        if state == AdapterState.FAILED:
            failed.set()

    try:
        await client.start(lambda _event: asyncio.sleep(0), report)
        await asyncio.wait_for(failed.wait(), timeout=2)
    finally:
        await client.stop()
        await runner.cleanup()

    assert states[-1] == AdapterState.FAILED

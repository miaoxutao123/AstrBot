"""QQ Official IDENTIFY, RESUME, invalid-session, and heartbeat protocol tests."""

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import pytest

from gateway.adapters.qq_official.common.errors import QQOfficialTimeoutError
from gateway.adapters.qq_official.websocket.client import TencentGatewayClient
from gateway.adapters.qq_official.websocket.config import QQOfficialWebSocketConfig
from gateway.core import AdapterState


class FakeSocket:
    def __init__(self, messages: list[Mapping[str, Any]]) -> None:
        self.messages = [json.dumps(message) for message in messages]
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def __aiter__(self) -> "FakeSocket":
        return self

    async def __anext__(self) -> str:
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)

    async def send(self, value: str) -> None:
        self.sent.append(json.loads(value))

    async def close(self) -> None:
        self.closed = True


def config() -> QQOfficialWebSocketConfig:
    return QQOfficialWebSocketConfig.from_mapping(
        {"app_id": {"env": "APP"}, "secret": {"env": "SECRET"}}
    )


async def test_identify_ready_dispatch_and_reconnect_opcode() -> None:
    client = TencentGatewayClient(config(), "app", "secret", "token", 9999999999)
    socket = FakeSocket(
        [
            {"op": 10, "d": {"heartbeat_interval": 10000}},
            {
                "op": 0,
                "t": "READY",
                "s": 1,
                "d": {
                    "session_id": "session",
                    "resume_gateway_url": "wss://resume.invalid",
                },
            },
            {"op": 0, "t": "C2C_MESSAGE_CREATE", "s": 2, "d": {"id": "m"}},
            {"op": 7},
        ]
    )
    dispatched: list[str] = []
    states: list[AdapterState] = []
    sessions: list[tuple[str | None, int | None, str | None]] = []

    async def dispatch(event_type: str, _data: Mapping[str, Any]) -> None:
        dispatched.append(event_type)

    client._session_handler = lambda session, sequence, resume: _append_session(
        sessions, session, sequence, resume
    )
    reconnect = await client._connection(
        socket, dispatch, lambda state, _reason: states.append(state)
    )
    assert reconnect
    assert socket.sent[0]["op"] == 2
    assert socket.sent[0]["d"]["token"] == "QQBot token"
    assert dispatched == ["C2C_MESSAGE_CREATE"]
    assert states == [AdapterState.RUNNING]
    assert sessions[-1] == ("session", 2, "wss://resume.invalid")


async def _append_session(
    values: list[tuple[str | None, int | None, str | None]],
    session: str | None,
    sequence: int | None,
    resume: str | None,
) -> None:
    values.append((session, sequence, resume))


async def test_resume_and_invalid_session_clear_state() -> None:
    client = TencentGatewayClient(
        config(),
        "app",
        "secret",
        "token",
        9999999999,
        "saved-session",
        42,
        "wss://resume.invalid",
    )
    sessions: list[tuple[str | None, int | None, str | None]] = []
    client._session_handler = lambda session, sequence, resume: _append_session(
        sessions, session, sequence, resume
    )
    socket = FakeSocket(
        [
            {"op": 10, "d": {"heartbeat_interval": 10000}},
            {"op": 0, "t": "RESUMED", "s": 43, "d": {}},
            {"op": 9, "d": False},
        ]
    )

    async def ignore(_event_type: str, _data: Mapping[str, Any]) -> None:
        return None

    assert await client._connection(socket, ignore, lambda _state, _reason: None)
    assert socket.sent[0]["op"] == 6
    assert socket.sent[0]["d"]["session_id"] == "saved-session"
    assert sessions[-1] == (None, None, None)
    assert client.session_id is None and client.sequence is None


async def test_heartbeat_timeout_closes_socket() -> None:
    client = TencentGatewayClient(config(), "app", "secret", "token", 9999999999)
    socket = FakeSocket([])
    acknowledgements = [True]
    task = asyncio.create_task(client._heartbeat(socket, 0.001, acknowledgements))
    with pytest.raises(QQOfficialTimeoutError):
        await asyncio.wait_for(task, 0.1)
    assert socket.sent[0] == {"op": 1, "d": None}
    assert socket.closed

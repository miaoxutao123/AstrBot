"""aiocqhttp reverse WebSocket lifecycle compatibility test."""

import asyncio
import socket

import pytest

from gateway.adapters.onebot.client import ReverseWebSocketClient
from gateway.adapters.onebot.config import OneBotConfig


@pytest.mark.asyncio
async def test_reverse_client_starts_and_shuts_down_cleanly() -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    client = ReverseWebSocketClient(
        OneBotConfig.from_mapping(
            {
                "mode": "reverse_websocket",
                "host": "127.0.0.1",
                "port": port,
            }
        ),
        None,
    )

    await client.start(lambda _event: asyncio.sleep(0), lambda _state, _reason: None)
    await asyncio.sleep(0.05)
    await client.stop()

"""Telegram polling client lifecycle and SDK error tests."""

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from telegram.error import InvalidToken, NetworkError

from gateway.adapters.telegram.client import TelegramPollingClient
from gateway.adapters.telegram.config import TelegramConfig
from gateway.core import AdapterState


class FakeBot:
    async def get_me(self) -> dict[str, int]:
        return {"id": 1}


class FakeUpdater:
    def __init__(self) -> None:
        self.running = False
        self.error_callback: Callable[[Exception], None] | None = None

    async def start_polling(self, **params: Any) -> None:
        self.error_callback = params["error_callback"]
        self.running = True

    async def stop(self) -> None:
        self.running = False


class FakeApplication:
    def __init__(self, initialize_error: Exception | None = None) -> None:
        self.updater = FakeUpdater()
        self.bot = FakeBot()
        self.running = False
        self.initialize_error = initialize_error
        self.shutdown_complete = False

    async def initialize(self) -> None:
        if self.initialize_error is not None:
            raise self.initialize_error

    async def start(self) -> None:
        self.running = True

    async def stop(self) -> None:
        self.running = False

    async def shutdown(self) -> None:
        self.shutdown_complete = True


def config() -> TelegramConfig:
    return TelegramConfig.from_mapping(
        {
            "token": {"env": "TELEGRAM_TOKEN"},
            "health_interval": 0.01,
            "reconnect_max_delay": 0.01,
        }
    )


async def wait_until(predicate: Callable[[], bool]) -> None:
    for _attempt in range(100):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not reached")


@pytest.mark.asyncio
async def test_polling_health_reports_disconnect_recovery_and_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = FakeApplication()
    client = TelegramPollingClient(config(), "123:token")
    monkeypatch.setattr(client, "_build_application", lambda: application)
    states: list[AdapterState] = []

    await client.start(
        lambda _update: asyncio.sleep(0), lambda state, _reason: states.append(state)
    )
    await wait_until(lambda: AdapterState.RUNNING in states)
    assert application.updater.error_callback is not None
    application.updater.error_callback(NetworkError("offline"))
    await wait_until(lambda: AdapterState.DEGRADED in states)
    await wait_until(lambda: states.count(AdapterState.RUNNING) >= 2)
    await client.stop()

    assert application.shutdown_complete
    assert not application.updater.running


@pytest.mark.asyncio
async def test_polling_invalid_token_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = FakeApplication(InvalidToken("invalid"))
    client = TelegramPollingClient(config(), "invalid")
    monkeypatch.setattr(client, "_build_application", lambda: application)
    states: list[AdapterState] = []

    await client.start(
        lambda _update: asyncio.sleep(0), lambda state, _reason: states.append(state)
    )
    await wait_until(lambda: AdapterState.FAILED in states)
    await client.stop()

    assert states[-1] == AdapterState.FAILED

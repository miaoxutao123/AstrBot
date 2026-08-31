"""Deterministic OneBot client used by adapter integration tests."""

from collections.abc import Mapping
from typing import Any

from gateway.adapters.onebot.client import EventHandler, StateHandler
from gateway.core import AdapterState


class FakeOneBotClient:
    """Record actions and expose explicit connection transitions.

    Args:
        startup_state: State reported during start.
    """

    def __init__(self, startup_state: AdapterState = AdapterState.RUNNING) -> None:
        self.startup_state = startup_state
        self.actions: list[tuple[str, dict[str, Any]]] = []
        self.stopped = False
        self._on_event: EventHandler | None = None
        self._report_state: StateHandler | None = None

    async def start(
        self,
        on_event: EventHandler,
        report_state: StateHandler,
    ) -> None:
        """Store callbacks and report the configured startup state.

        Args:
            on_event: Async inbound event callback.
            report_state: Adapter health callback.
        """
        self._on_event = on_event
        self._report_state = report_state
        reason = (
            "OneBot access token was rejected"
            if self.startup_state == AdapterState.FAILED
            else None
        )
        report_state(self.startup_state, reason)

    async def stop(self) -> None:
        """Record deterministic shutdown."""
        self.stopped = True

    async def call_action(self, action: str, **params: Any) -> Mapping[str, Any]:
        """Record an action and return deterministic protocol data.

        Args:
            action: OneBot action name.
            **params: Action parameters.

        Returns:
            File URL or send message ID.
        """
        self.actions.append((action, params))
        if action == "get_group_file_url":
            return {"url": "https://example.test/report.txt"}
        return {"message_id": 9001}

    async def download(
        self,
        url: str,
        max_size: int,
    ) -> tuple[bytes, str, str]:
        """Return deterministic bounded media.

        Args:
            url: Fixture URL.
            max_size: Maximum bytes.

        Returns:
            Content, MIME type, and filename.
        """
        data = b"image" if url.endswith(".jpg") else b"report"
        assert len(data) <= max_size
        if url.endswith(".jpg"):
            return data, "image/jpeg", "photo.jpg"
        return data, "text/plain", "report.txt"

    async def emit(self, event: Mapping[str, Any]) -> None:
        """Deliver a fixture event.

        Args:
            event: OneBot event mapping.
        """
        assert self._on_event is not None
        await self._on_event(event)

    def disconnect(self) -> None:
        """Report a simulated disconnect."""
        assert self._report_state is not None
        self._report_state(AdapterState.DEGRADED, "websocket disconnected")

    def reconnect(self) -> None:
        """Report a simulated reconnection."""
        assert self._report_state is not None
        self._report_state(AdapterState.RUNNING, None)

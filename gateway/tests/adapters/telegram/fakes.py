"""Deterministic Telegram client for adapter integration tests."""

from collections.abc import Mapping
from typing import Any

from gateway.adapters.telegram.client import StateHandler, UpdateHandler
from gateway.core import AdapterState


class FakeTelegramClient:
    """Record Bot API calls and emit normalized updates."""

    def __init__(self, initial_state: AdapterState = AdapterState.RUNNING) -> None:
        self.initial_state = initial_state
        self.on_update: UpdateHandler | None = None
        self.report_state: StateHandler | None = None
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.downloads: dict[str, tuple[bytes, str, str]] = {
            "photo-file": (b"photo", "image/jpeg", "photo.jpg"),
            "document-file": (b"document", "text/plain", "report.txt"),
            "audio-file": (b"audio", "audio/ogg", "voice.ogg"),
            "video-file": (b"video", "video/mp4", "video.mp4"),
        }
        self.stopped = False
        self.next_message_id = 700

    async def start(
        self,
        on_update: UpdateHandler,
        report_state: StateHandler,
    ) -> None:
        self.on_update = on_update
        self.report_state = report_state
        report_state(
            self.initial_state,
            None if self.initial_state.value == "running" else "test failure",
        )

    async def stop(self) -> None:
        self.stopped = True

    async def call(self, method: str, **params: Any) -> Mapping[str, Any]:
        self.calls.append((method, params))
        self.next_message_id += 1
        return {"message_id": self.next_message_id}

    async def download(
        self,
        file_id: str,
        max_size: int,
    ) -> tuple[bytes, str, str]:
        content = self.downloads[file_id]
        if len(content[0]) > max_size:
            raise ValueError("file too large")
        return content

    async def emit(self, update: Mapping[str, Any]) -> None:
        assert self.on_update is not None
        await self.on_update(update)

    def disconnect(self) -> None:
        assert self.report_state is not None
        self.report_state(AdapterState.DEGRADED, "network disconnected")

    def reconnect(self) -> None:
        assert self.report_state is not None
        self.report_state(AdapterState.RUNNING, None)

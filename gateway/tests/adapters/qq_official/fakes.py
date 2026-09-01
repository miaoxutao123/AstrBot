"""Deterministic QQ Official gateway/API client."""

from collections.abc import Mapping
from typing import Any

from gateway.adapters.qq_official.common.errors import QQOfficialRateLimitError
from gateway.adapters.qq_official.websocket.client import (
    CredentialHandler,
    DispatchHandler,
    SessionHandler,
    StateHandler,
)
from gateway.core import AdapterState


class FakeQQOfficialClient:
    def __init__(self) -> None:
        self.dispatch: DispatchHandler | None = None
        self.report_state: StateHandler | None = None
        self.credential: CredentialHandler | None = None
        self.session: SessionHandler | None = None
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.stopped = False
        self.rate_limit = False

    async def start(
        self,
        dispatch: DispatchHandler,
        report_state: StateHandler,
        credential: CredentialHandler,
        session: SessionHandler,
    ) -> None:
        self.dispatch = dispatch
        self.report_state = report_state
        self.credential = credential
        self.session = session
        await credential("dynamic-access-token", 9999999999)
        await session("session-1", 10, "wss://resume.example.invalid")
        report_state(AdapterState.RUNNING, None)

    async def stop(self) -> None:
        self.stopped = True

    async def request(
        self, method: str, path: str, data: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        if self.rate_limit:
            raise QQOfficialRateLimitError("limited", 2.5)
        self.calls.append((method, path, dict(data) if data is not None else None))
        if path.endswith("/files"):
            return {"file_info": "uploaded-file"}
        return {"id": "sent-qq-1"}

    async def download(
        self, url: str, max_size: int
    ) -> tuple[bytes, str | None, str | None]:
        content = b"qq-image"
        if len(content) > max_size:
            raise ValueError("too large")
        return content, "image/png", "qq.png"

    async def emit(self, event_type: str, data: Mapping[str, Any]) -> None:
        assert self.dispatch is not None
        await self.dispatch(event_type, data)

    async def invalid_session(self) -> None:
        assert self.session is not None
        await self.session(None, None, None)

    def disconnect(self) -> None:
        assert self.report_state is not None
        self.report_state(
            AdapterState.DEGRADED, "QQ Official disconnected; reconnecting"
        )

    def resume(self) -> None:
        assert self.report_state is not None
        self.report_state(AdapterState.RUNNING, None)

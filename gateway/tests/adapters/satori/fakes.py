"""Deterministic Satori protocol client."""

from collections.abc import Mapping
from typing import Any

from gateway.adapters.satori.client import EnvelopeHandler, StateHandler
from gateway.adapters.satori.errors import SatoriAuthenticationError
from gateway.adapters.satori.protocol import SatoriLogin
from gateway.core import AdapterState


class FakeSatoriClient:
    def __init__(self) -> None:
        self.handler: EnvelopeHandler | None = None
        self.report_state: StateHandler | None = None
        self.calls: list[tuple[str, str, dict[str, Any], SatoriLogin]] = []
        self.stopped = False
        self.fail_auth = False
        self.heartbeat_count = 1

    async def start(self, handler: EnvelopeHandler, report_state: StateHandler) -> None:
        self.handler = handler
        self.report_state = report_state
        report_state(AdapterState.RUNNING, None)

    async def stop(self) -> None:
        self.stopped = True

    async def call(
        self,
        method: str,
        path: str,
        data: Mapping[str, Any],
        login: SatoriLogin,
    ) -> Mapping[str, Any]:
        if self.fail_auth:
            raise SatoriAuthenticationError("invalid Satori token")
        self.calls.append((method, path, dict(data), login))
        return {"id": "sent-1"}

    async def download(
        self, url: str, max_size: int
    ) -> tuple[bytes, str | None, str | None]:
        content = b"image"
        if len(content) > max_size:
            raise ValueError("too large")
        return content, "image/png", "image.png"

    async def emit(self, envelope: Mapping[str, Any]) -> None:
        assert self.handler is not None
        await self.handler(envelope)

    def disconnect(self) -> None:
        assert self.report_state is not None
        self.report_state(AdapterState.DEGRADED, "Satori disconnected; reconnecting")

    def reconnect(self) -> None:
        assert self.report_state is not None
        self.report_state(AdapterState.RUNNING, None)

    def authentication_failure(self) -> None:
        assert self.report_state is not None
        self.report_state(AdapterState.FAILED, "Satori authentication was rejected")

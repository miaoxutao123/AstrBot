"""Public-wire closed loop: FakeIM -> SDK event -> SDK reply -> FakeIM command."""

# ruff: noqa: E402, I001

import asyncio
import socket
import sys
from pathlib import Path

import uvicorn

SDK_SOURCE = Path(__file__).parents[3] / "packages" / "python-sdk" / "src"
sys.path.insert(0, str(SDK_SOURCE))

from astrbot_gateway_sdk import AsyncGatewayClient  # type: ignore[import-not-found]

from gateway.api import ApiKey, create_app  # noqa: E402
from gateway.core import (  # noqa: E402
    AdapterDescriptor,
    AdapterRegistry,
    AdapterRuntime,
    Capability,
    MemoryEventBus,
)
from tests.fake_adapters import FakeIMAdapter  # noqa: E402


class SDKFakeIMAdapter(FakeIMAdapter):
    """Fake IM also advertising the standard profile operations used by the SDK."""

    @property
    def descriptor(self) -> AdapterDescriptor:
        descriptor = super().descriptor
        return type(descriptor)(
            descriptor.adapter_type,
            descriptor.name,
            descriptor.version,
            descriptor.api_version,
            descriptor.family,
            descriptor.capabilities
            + (Capability("im.message.send"), Capability("im.message.reply")),
        )


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def test_sdk_reply_closed_loop() -> None:
    bus = MemoryEventBus()
    registry = AdapterRegistry()
    adapter = SDKFakeIMAdapter()
    registry.register(adapter.instance_id, adapter)
    app = create_app(
        AdapterRuntime(registry, bus),
        bus,
        [ApiKey("agent", "agent-secret", frozenset({"*"}))],
    )
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    server_task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        else:
            raise TimeoutError("test Gateway server did not start")
        async with AsyncGatewayClient(
            f"http://127.0.0.1:{port}", api_key="agent-secret"
        ) as gateway:
            stream = gateway.events(event_type="im.message")
            received = asyncio.create_task(anext(stream))
            await asyncio.sleep(0.02)
            await adapter.emit_message("user:1", "hello", "inbound-1")
            event = await asyncio.wait_for(received, 2)
            result = await gateway.reply(event, "echo: hello")
            await stream.aclose()
    finally:
        server.should_exit = True
        await asyncio.sleep(0.05)
        if not server_task.done():
            server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)

    assert result["status"] == "success"
    command = adapter.commands[-1]
    assert command.type == "im.message.reply"
    assert command.correlation_id == event.id
    assert command.payload.data["reply_to"] == "inbound-1"

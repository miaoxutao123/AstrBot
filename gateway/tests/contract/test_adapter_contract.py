"""Shared contract tests required of every Phase 1 adapter."""

import logging

import pytest

from gateway.core import (
    GATEWAY_API_STABILITY,
    GATEWAY_API_VERSION,
    AdapterContext,
    EndpointRef,
    GatewayCommand,
    GatewayEvent,
    Payload,
)
from gateway.media import MemoryMediaStore
from gateway.profiles.im import IMOutboundMessage, IMSegment
from gateway.secrets import MemorySecretStore, NamespacedSecretStore
from gateway.state import MemoryStateStore, NamespacedStateStore
from tests.fake_adapters import FakeIMAdapter, FakeRobotAdapter, FakeSensorAdapter
from tests.fake_adapters.base import RecordingAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter",
    [FakeIMAdapter(), FakeSensorAdapter(), FakeRobotAdapter()],
    ids=["im", "sensor", "robot"],
)
async def test_adapter_contract(adapter: RecordingAdapter) -> None:
    emitted: list[GatewayEvent] = []

    async def emit(event: GatewayEvent) -> None:
        emitted.append(event)

    context = AdapterContext(
        family=adapter.descriptor.family,
        adapter_type=adapter.descriptor.adapter_type,
        adapter_id=adapter.instance_id,
        emit=emit,
        logger=logging.getLogger("test.adapter"),
        get_secret=lambda key: {"TOKEN": "secret"}.get(key),
        report_state=lambda _state, _reason: None,
        state=NamespacedStateStore(MemoryStateStore(), adapter.instance_id),
        secrets=NamespacedSecretStore(MemorySecretStore(), adapter.instance_id),
        media=MemoryMediaStore(),
    )
    assert adapter.descriptor.api_version == GATEWAY_API_VERSION
    assert GATEWAY_API_STABILITY == "stable"
    assert adapter.descriptor.adapter_type
    assert adapter.descriptor.family
    assert adapter.descriptor.capabilities

    await adapter.start(context)
    endpoint = EndpointRef(
        adapter.descriptor.family,
        adapter.descriptor.adapter_type,
        adapter.instance_id,
        "endpoint-1",
    )
    capabilities = await adapter.capabilities(endpoint)
    payload = Payload("contract.command.v1")
    if adapter.descriptor.family == "im":
        payload = IMOutboundMessage((IMSegment.text("contract"),)).to_payload()
    command = GatewayCommand(
        target=endpoint,
        type=capabilities[0].name,
        payload=payload,
    )
    result = await adapter.execute(command)
    event = GatewayEvent(
        source=endpoint,
        type="contract.event",
        payload=Payload("contract.event.v1"),
    )
    await adapter.emit(event)
    await adapter.stop()

    assert result.command_id == command.id
    assert result.status == "success"
    assert emitted == [event]
    assert not adapter.started


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        EndpointRef("robot", "fake-sensor", "sensor-main", "temperature/1"),
        EndpointRef("sensor", "mqtt", "sensor-main", "temperature/1"),
        EndpointRef("sensor", "fake-sensor", "other-adapter", "temperature/1"),
    ],
    ids=["family", "adapter-type", "adapter-id"],
)
async def test_adapter_context_rejects_spoofed_source(source: EndpointRef) -> None:
    async def emit(_event: GatewayEvent) -> None:
        return None

    context = AdapterContext(
        family="sensor",
        adapter_type="fake-sensor",
        adapter_id="sensor-main",
        emit=emit,
        logger=logging.getLogger("test.adapter"),
        get_secret=lambda _key: None,
        report_state=lambda _state, _reason: None,
        state=NamespacedStateStore(MemoryStateStore(), "sensor-main"),
        secrets=NamespacedSecretStore(MemorySecretStore(), "sensor-main"),
        media=MemoryMediaStore(),
    )
    spoofed = GatewayEvent(
        source=source,
        type="telemetry.temperature",
        payload=Payload("sensor.temperature.v1", {"value": 20}),
    )

    with pytest.raises(ValueError):
        await context.emit(spoofed)


@pytest.mark.asyncio
async def test_adapter_rejects_foreign_type_and_instance_capability_queries() -> None:
    adapter = FakeIMAdapter("im-main")
    assert (
        await adapter.capabilities(
            EndpointRef("im", "telegram", "im-main", "private:1")
        )
        == []
    )
    assert (
        await adapter.capabilities(
            EndpointRef("im", "fake-im", "im-other", "private:1")
        )
        == []
    )

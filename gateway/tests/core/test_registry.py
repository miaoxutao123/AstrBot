"""Unit tests for adapter registration and factory boundaries."""

import pytest

from gateway.core import AdapterRegistry, GatewayException
from tests.fake_adapters import FakeRobotAdapter


def test_registry_creates_adapter_from_factory() -> None:
    registry = AdapterRegistry()
    registry.register_factory("fake-robot", FakeRobotAdapter)

    adapter = registry.create("lab-robot", "fake-robot", {"port": "test"})

    assert adapter is registry.get("lab-robot")
    assert registry.factory_types() == ["fake-robot"]
    assert registry.instances() == [("lab-robot", adapter)]


def test_registry_rejects_duplicate_instance() -> None:
    registry = AdapterRegistry()
    registry.register("robot-main", FakeRobotAdapter())

    with pytest.raises(ValueError):
        registry.register("robot-main", FakeRobotAdapter())


def test_registry_returns_stable_not_found_error() -> None:
    registry = AdapterRegistry()

    with pytest.raises(GatewayException) as raised:
        registry.get("missing")

    assert raised.value.error.code.value == "ADAPTER_NOT_FOUND"

"""Unit tests for adapter registration and factory boundaries."""

from collections.abc import Callable
from typing import Any

import pytest

from gateway.core import AdapterRegistry, GatewayException
from tests.fake_adapters import FakeRobotAdapter


class FakeEntryPoint:
    """Small importlib entry-point stand-in."""

    def __init__(self, name: str, loader: Callable[[], Any]) -> None:
        self.name = name
        self._loader = loader

    def load(self) -> Any:
        """Return or raise from the configured loader.

        Returns:
            Loaded entry-point object.
        """
        return self._loader()


class FakeEntryPoints(list[FakeEntryPoint]):
    """Entry-point collection implementing Python's select API."""

    def select(self, *, group: str) -> "FakeEntryPoints":
        """Return entries for the expected adapter group.

        Args:
            group: Requested entry-point group.

        Returns:
            This fake collection.
        """
        assert group == "agent_gateway.adapters"
        return self


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


def test_discovery_isolates_broken_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AdapterRegistry()

    def fail_load() -> Any:
        raise ImportError("optional SDK is missing")

    entry_points = FakeEntryPoints(
        [
            FakeEntryPoint("working-one", lambda: FakeRobotAdapter),
            FakeEntryPoint("broken", fail_load),
            FakeEntryPoint("working-two", lambda: FakeRobotAdapter),
        ]
    )
    monkeypatch.setattr(
        "gateway.core.registry.metadata.entry_points",
        lambda: entry_points,
    )

    result = registry.discover()

    assert result.loaded == ("working-one", "working-two")
    assert result.failed == ("broken",)
    assert result.errors == {"broken": "optional SDK is missing"}
    assert registry.factory_types() == ["working-one", "working-two"]

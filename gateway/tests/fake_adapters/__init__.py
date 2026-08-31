"""Fake adapters used by Core and contract tests."""

from .fake_im import FakeIMAdapter
from .fake_robot import FakeRobotAdapter
from .fake_sensor import FakeSensorAdapter

__all__ = ["FakeIMAdapter", "FakeRobotAdapter", "FakeSensorAdapter"]

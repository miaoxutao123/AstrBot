"""Security regression tests for external Agent enrollment credentials."""

from pathlib import Path

import pytest

from gateway.control_plane import AgentRegistry


def test_enrollment_is_hashed_single_use_and_revocable(tmp_path: Path) -> None:
    registry = AgentRegistry(tmp_path / "agents.db")
    enrollment = registry.create_enrollment("DSH", ["adapters:read"], 60)
    assert enrollment["token"] not in (tmp_path / "agents.db").read_bytes().decode(
        "latin1"
    )
    registered = registry.register(enrollment["token"], {"display_name": "DSH"})
    assert registry.authenticate(registered["api_key"]) == (
        registered["agent_id"],
        frozenset({"adapters:read"}),
    )
    with pytest.raises(ValueError, match="consumed"):
        registry.register(enrollment["token"], {})
    registry.revoke(registered["agent_id"])
    assert registry.authenticate(registered["api_key"]) is None


def test_heartbeat_is_bounded_and_changes_presence(tmp_path: Path) -> None:
    registry = AgentRegistry(tmp_path / "agents.db")
    enrollment = registry.create_enrollment("agent", [], 60)
    registered = registry.register(enrollment["token"], {})
    registry.heartbeat(registered["agent_id"], {"bridge": {"state": "running"}})
    assert registry.list_agents()[0]["status"] == "ONLINE"
    with pytest.raises(ValueError, match="16 KiB"):
        registry.heartbeat(registered["agent_id"], {"data": "x" * 20000})

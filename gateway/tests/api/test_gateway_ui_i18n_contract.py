"""Minimal regression checks for Gateway control-plane localization wiring."""

from pathlib import Path


ROOT = Path(__file__).parents[3]
GATEWAY_UI = ROOT / "dashboard" / "src" / "gateway"


def test_gateway_agents_page_has_no_remaining_primary_english_actions() -> None:
    source = (GATEWAY_UI / "GatewayAgentsPage.vue").read_text(encoding="utf-8")
    assert ">Revoke<" not in source
    assert "Create Agent Enrollment" not in source


def test_gateway_connections_page_has_no_remaining_primary_english_actions() -> None:
    source = (GATEWAY_UI / "GatewayConnectionsPage.vue").read_text(encoding="utf-8")
    assert ">Start<" not in source
    assert ">Authentication<" not in source

"""Stable API-layer links for generic Gateway integrations."""

API_BASE = "/v1"
DISCOVERY_PATH = f"{API_BASE}/discovery"
EVENTS_WS_PATH = f"{API_BASE}/events/ws"
COMMANDS_PATH = f"{API_BASE}/commands"
AGENT_REGISTER_PATH = f"{API_BASE}/agents/register"
AGENT_BOOTSTRAP_PATH = f"{API_BASE}/agent/bootstrap"
AGENT_SELF_PATH = f"{API_BASE}/agents/me"
AGENT_HEARTBEAT_PATH = f"{API_BASE}/agents/me/heartbeat"
DEFAULT_IM_EVENT_FILTER = {"family": "im", "event_type": "im.message"}


def integration_links() -> dict[str, str]:
    """Return stable runtime links without exposing credentials."""
    return {
        "api": API_BASE,
        "register": AGENT_REGISTER_PATH,
        "bootstrap": AGENT_BOOTSTRAP_PATH,
        "discovery": DISCOVERY_PATH,
        "events": EVENTS_WS_PATH,
        "commands": COMMANDS_PATH,
        "self": AGENT_SELF_PATH,
        "heartbeat": AGENT_HEARTBEAT_PATH,
    }

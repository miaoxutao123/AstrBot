"""Stable API-layer links for generic Gateway integrations."""

API_BASE = "/v1"
DISCOVERY_PATH = f"{API_BASE}/discovery"
EVENTS_WS_PATH = f"{API_BASE}/events/ws"
COMMANDS_PATH = f"{API_BASE}/commands"
AGENT_REGISTER_PATH = f"{API_BASE}/agents/register"
AGENT_BOOTSTRAP_PATH = f"{API_BASE}/agent/bootstrap"
AGENT_SELF_PATH = f"{API_BASE}/agents/me"
AGENT_HEARTBEAT_PATH = f"{API_BASE}/agents/me/heartbeat"
AGENT_INTEGRATION_PROTOCOL = "astrbot.gateway.agent-integration.v1"
AGENT_INTEGRATION_DOC_PATH = "/docs/agent-integration"
AGENT_COMMAND_EXAMPLE_PATH = "/docs/agent-integration/examples/command-python"
AGENT_HTTP_EXAMPLE_PATH = "/docs/agent-integration/examples/http-python"
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


def agent_integration_contract() -> dict[str, object]:
    """Return the stable, Agent-owned integration boundary for v1."""
    return {
        "protocol": AGENT_INTEGRATION_PROTOCOL,
        "invoke": {
            "schema": "astrbot.agent.invoke.v1",
            "supported_modes": ["command", "http"],
        },
        "result": {"schema": "astrbot.agent.result.v1"},
        "session": {"gateway_session_key": True, "external_session_id": True},
        "proactive": {"supported": True, "commands": COMMANDS_PATH},
        "documentation": AGENT_INTEGRATION_DOC_PATH,
        "examples": {
            "command_python": AGENT_COMMAND_EXAMPLE_PATH,
            "http_python": AGENT_HTTP_EXAMPLE_PATH,
        },
        "validation": {
            "doctor": "astrbot-gateway-agent doctor --config agent-gateway.yaml",
            "invoke_example": {
                "schema": "astrbot.agent.invoke.v1",
                "session": {"key": "doctor/session", "external_session_id": None},
                "input": {
                    "type": "im.message",
                    "text": "doctor-session-turn-1",
                    "segments": [
                        {"type": "text", "data": {"text": "doctor-session-turn-1"}}
                    ],
                    "event": {},
                },
                "context": {"gateway_url": "<gateway-url>"},
            },
            "expected_result_schema": "astrbot.agent.result.v1",
        },
    }

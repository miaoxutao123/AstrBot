"""Public, non-sensitive Agent Bootstrap manifest."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from .bootstrap_contract import (
    AGENT_BOOTSTRAP_PATH,
    AGENT_HEARTBEAT_PATH,
    AGENT_REGISTER_PATH,
    AGENT_SELF_PATH,
    API_BASE,
    COMMANDS_PATH,
    DEFAULT_IM_EVENT_FILTER,
    DISCOVERY_PATH,
    EVENTS_WS_PATH,
)

router = APIRouter(tags=["bootstrap"])


@router.get("/.well-known/astrbot-gateway")
async def well_known() -> dict[str, object]:
    """Expose stable bootstrap links without runtime inventory or credentials."""
    return {
        "protocol": "astrbot-gateway-agent-bootstrap.v1",
        "gateway_api": API_BASE,
        "authenticated_bootstrap": AGENT_BOOTSTRAP_PATH,
        "authentication": {"type": "bearer", "api_key_env": "GATEWAY_API_KEY"},
        "discovery": DISCOVERY_PATH,
        "events": EVENTS_WS_PATH,
        "commands": COMMANDS_PATH,
        "agent_registration": {
            "endpoint": AGENT_REGISTER_PATH,
            "enrollment_env": "GATEWAY_ENROLLMENT_TOKEN",
            "self": AGENT_SELF_PATH,
            "heartbeat": AGENT_HEARTBEAT_PATH,
        },
        "profiles": {
            "im": {
                "ordinary_message_event": "im.message",
                "default_event_filter": DEFAULT_IM_EVENT_FILTER,
            }
        },
        "integration": {
            "python_sdk": "astrbot-gateway-sdk",
            "mcp": "astrbot-gateway-mcp",
            "agent_bridge": "astrbot-gateway-agent",
        },
        "documentation": {"bootstrap": "/docs/agent-bootstrap"},
    }


@router.get("/docs/agent-bootstrap", response_class=PlainTextResponse)
async def bootstrap_guide() -> str:
    """Serve the Agent-oriented bootstrap instructions advertised in manifest."""
    return """# AstrBot Gateway Agent Bootstrap
1. Read this manifest and GATEWAY_API_KEY from your environment.
2. Call /v1/agent/bootstrap then /v1/discovery with Bearer authentication.
3. Install astrbot-gateway-agent and optionally astrbot-gateway-mcp.
4. Create your own command or HTTP wrapper for astrbot.agent.invoke.v1.
5. Run astrbot-gateway-agent doctor, then run the Bridge and verify a reply.
For first-time registration, use GATEWAY_ENROLLMENT_TOKEN with
POST /v1/agents/register; then use the returned key for /v1/agents/me and
/v1/agents/me/heartbeat.
"""

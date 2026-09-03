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
1. GET /.well-known/astrbot-gateway from the Gateway base URL.
2. Do not guess or probe undocumented Gateway endpoints.
3. Read the registration link from the manifest and submit GATEWAY_ENROLLMENT_TOKEN.
4. Store the returned independent Agent API key in GATEWAY_API_KEY.
5. Follow the bootstrap link returned by registration; it is the authoritative runtime manifest.
6. Ordinary IM messages use family=im and event_type=im.message.
7. Install astrbot-gateway-agent, provide an astrbot.agent.invoke.v1 wrapper,
then run doctor and the Bridge.
"""

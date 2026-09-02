"""Public, non-sensitive Agent Bootstrap manifest."""

from fastapi import APIRouter

router = APIRouter(tags=["bootstrap"])


@router.get("/.well-known/astrbot-gateway")
async def well_known() -> dict[str, object]:
    """Expose stable bootstrap links without runtime inventory or credentials."""
    return {
        "protocol": "astrbot-gateway-agent-bootstrap.v1", "gateway_api": "/v1",
        "authentication": {"type": "bearer", "api_key_env": "GATEWAY_API_KEY"},
        "discovery": "/v1/discovery", "events": "/v1/events/ws", "commands": "/v1/commands",
        "integration": {"python_sdk": "astrbot-gateway-sdk", "mcp": "astrbot-gateway-mcp", "agent_bridge": "astrbot-gateway-agent"},
        "documentation": {"bootstrap": "/docs/agent-bootstrap"},
    }

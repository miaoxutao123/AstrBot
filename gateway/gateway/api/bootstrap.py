"""Public, non-sensitive Agent Bootstrap manifest."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["bootstrap"])


@router.get("/.well-known/astrbot-gateway")
async def well_known() -> dict[str, object]:
    """Expose stable bootstrap links without runtime inventory or credentials."""
    return {
        "protocol": "astrbot-gateway-agent-bootstrap.v1",
        "gateway_api": "/v1",
        "authentication": {"type": "bearer", "api_key_env": "GATEWAY_API_KEY"},
        "discovery": "/v1/discovery",
        "events": "/v1/events/ws",
        "commands": "/v1/commands",
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
"""

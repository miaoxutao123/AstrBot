"""External Agent enrollment, presence and administrator APIs."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Body, Depends, Request

from .auth import ApiPrincipal
from .bootstrap_contract import DEFAULT_IM_EVENT_FILTER, integration_links
from .dependencies import get_services, require_scope

router = APIRouter(prefix="/v1", tags=["agents"])


def _registry(request: Request) -> Any:
    registry = get_services(request).agents
    if registry is None:
        raise RuntimeError("Agent Registry is not configured")
    return registry


@router.post("/agent-enrollments")
async def create_enrollment(
    _principal: Annotated[ApiPrincipal, Depends(require_scope("agents:manage"))],
    request: Request,
    body: dict[str, Any] = Body(),
) -> dict[str, Any]:
    return dict(
        _registry(request).create_enrollment(
            str(body.get("name_hint", "")),
            list(body.get("scopes", ["adapters:read", "events:read", "commands:send"])),
            float(body.get("ttl_seconds", 600)),
        )
    )


@router.post("/agents/register")
async def register_agent(
    request: Request, body: dict[str, Any] = Body()
) -> dict[str, Any]:
    result = _registry(request).register(
        str(body.get("enrollment_token", "")), dict(body.get("descriptor", {}))
    )
    return {**result, "gateway": integration_links(), "default_event_filter": DEFAULT_IM_EVENT_FILTER}


@router.get("/agents")
async def list_agents(
    _principal: Annotated[ApiPrincipal, Depends(require_scope("agents:read"))],
    request: Request,
) -> dict[str, Any]:
    return {"agents": _registry(request).list_agents()}


@router.get("/agents/{agent_id}")
async def get_agent(
    _principal: Annotated[ApiPrincipal, Depends(require_scope("agents:read"))],
    agent_id: str,
    request: Request,
) -> dict[str, Any]:
    agent = _registry(request).get_agent(agent_id)
    if agent is None:
        raise ValueError("agent was not found")
    return cast(dict[str, Any], agent)


@router.post("/agents/{agent_id}/revoke")
async def revoke_agent(
    _principal: Annotated[ApiPrincipal, Depends(require_scope("agents:manage"))],
    agent_id: str,
    request: Request,
) -> dict[str, str]:
    _registry(request).revoke(agent_id)
    return {"status": "revoked"}


@router.get("/agents/me")
async def agent_me(
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:read"))],
) -> dict[str, Any]:
    return _registry(request).get_agent(principal.key_id) or {}


@router.patch("/agents/me")
async def update_agent_me(
    principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:read"))],
    request: Request,
    body: dict[str, Any] = Body(),
) -> dict[str, Any]:
    # Descriptor is Agent-owned observability metadata. Grant scope and key
    # material stay server-owned and cannot be patched through this endpoint.
    descriptor = dict(body.get("descriptor", body))
    descriptor.pop("scopes", None)
    descriptor.pop("agent_id", None)
    descriptor.pop("api_key", None)
    _registry(request).update_descriptor(principal.key_id, descriptor)
    return _registry(request).get_agent(principal.key_id) or {}


@router.post("/agents/me/heartbeat")
async def heartbeat(
    principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:read"))],
    request: Request,
    body: dict[str, Any] = Body(),
) -> dict[str, str]:
    _registry(request).heartbeat(principal.key_id, body)
    return {"status": "ok"}

"""Agent-facing aggregate discovery routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from gateway import __version__
from gateway.profiles.capability_traits import (
    CapabilityTrait,
    capability_trait,
    direction_for,
)

from .auth import ApiPrincipal
from .bootstrap_contract import (
    DEFAULT_IM_EVENT_FILTER,
    agent_integration_contract,
    integration_links,
)
from .dependencies import get_services, require_scope
from .serialization import endpoint_resource_id, endpoint_to_dict

router = APIRouter(prefix="/v1", tags=["discovery"])


def _authorized(principal: ApiPrincipal, trait: CapabilityTrait | None) -> bool:
    """Require every declared capability scope; unknown means not authorized."""
    return trait is not None and all(
        principal.allows(scope) for scope in trait.required_scopes
    )


async def _inventory(request: Request, principal: ApiPrincipal) -> dict[str, Any]:
    services = get_services(request)
    adapter_items: list[dict[str, Any]] = []
    for info in services.runtime.list_info():
        capabilities = await services.runtime.capabilities(info.adapter_id)
        traits = [capability_trait(item.name, info.family) for item in capabilities]
        supported = direction_for(traits)
        authorized_traits = [trait for trait in traits if _authorized(principal, trait)]
        adapter_items.append(
            {
                "family": info.family,
                "adapter_type": info.adapter_type,
                "adapter_id": info.adapter_id,
                "state": info.state.value,
                "supported_direction": supported,
                "effective_direction": direction_for(authorized_traits),
            }
        )
    endpoints: list[dict[str, Any]] = []
    for record in services.events.endpoints():
        endpoint = record.endpoint
        capabilities = await services.runtime.capabilities(
            endpoint.adapter_id, endpoint
        )
        items = []
        traits = []
        for capability in capabilities:
            trait = capability_trait(capability.name, endpoint.family)
            traits.append(trait)
            items.append(
                {
                    "name": capability.name,
                    "version": capability.version,
                    "schema": capability.schema,
                    "direction": trait.direction if trait else "unknown",
                    "supported": True,
                    "authorized": _authorized(principal, trait),
                }
            )
        endpoints.append(
            {
                **endpoint_to_dict(endpoint),
                "id": endpoint_resource_id(endpoint),
                "capabilities": items,
                "direction": direction_for(
                    [trait for trait, item in zip(traits, items) if item["authorized"]]
                ),
            }
        )
    return {
        "gateway": {"version": __version__, "adapter_api": 1},
        "access": {
            "events_read": principal.allows("events:read"),
            "commands_send": principal.allows("commands:send"),
            "hardware_control": principal.allows("hardware:control"),
        },
        "adapters": adapter_items,
        "endpoints": endpoints,
    }


@router.get("/discovery")
async def discover(
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:read"))],
) -> dict[str, Any]:
    """Return the complete authorized public transport inventory."""
    return await _inventory(request, principal)


@router.get("/agent/bootstrap")
async def agent_bootstrap(
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:read"))],
) -> dict[str, Any]:
    """Return authenticated, machine-readable agent bootstrap instructions."""
    return {
        "protocol": "astrbot-gateway-agent-bootstrap.v1",
        "gateway": integration_links(),
        "agent": {
            "self": integration_links()["self"],
            "heartbeat": integration_links()["heartbeat"],
        },
        "subscriptions": {"ordinary_im_messages": DEFAULT_IM_EVENT_FILTER},
        "access": (inventory := await _inventory(request, principal))["access"],
        "inventory": inventory,
        "recommended_integration": {"bridge": True, "mcp": True},
        "agent_integration": agent_integration_contract(),
        "agent_registration": {"endpoint": integration_links()["register"]},
        "commands": {
            "install_bridge": "pip install astrbot-gateway-agent",
            "install_mcp": "pip install astrbot-gateway-mcp",
            "doctor": "astrbot-gateway-agent doctor --config agent-gateway.yaml",
        },
    }

"""Observed endpoint and capability routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from gateway.core import GatewayError, GatewayErrorCode

from .auth import ApiPrincipal
from .dependencies import get_services, require_scope
from .errors import GatewayApiError
from .serialization import (
    capability_to_dict,
    endpoint_from_resource_id,
    endpoint_resource_id,
    endpoint_to_dict,
)

router = APIRouter(prefix="/v1/endpoints", tags=["endpoints"])


@router.get("")
async def list_endpoints(
    request: Request,
    _principal: Annotated[
        ApiPrincipal,
        Depends(require_scope("adapters:read")),
    ],
) -> dict[str, object]:
    """List endpoints observed from retained events.

    Args:
        request: Current FastAPI request.
        _principal: Authorized caller.

    Returns:
        Observed endpoint collection.
    """
    records = get_services(request).events.endpoints()
    return {
        "endpoints": [
            {
                "id": endpoint_resource_id(record.endpoint),
                "endpoint": endpoint_to_dict(record.endpoint),
                "last_event_id": record.last_event_id,
                "last_seen": record.last_seen,
            }
            for record in records
        ]
    }


@router.get("/{endpoint_id}/capabilities")
async def get_endpoint_capabilities(
    endpoint_id: str,
    request: Request,
    _principal: Annotated[
        ApiPrincipal,
        Depends(require_scope("adapters:read")),
    ],
) -> dict[str, object]:
    """Query capabilities for an opaque endpoint resource ID.

    Args:
        endpoint_id: Opaque ID returned by ``GET /v1/endpoints``.
        request: Current FastAPI request.
        _principal: Authorized caller.

    Returns:
        Endpoint and capability collection.

    Raises:
        GatewayApiError: If the endpoint ID is malformed or was not observed.
    """
    services = get_services(request)
    try:
        endpoint = endpoint_from_resource_id(endpoint_id)
    except ValueError as exc:
        raise GatewayApiError(
            404,
            GatewayError(
                GatewayErrorCode.ENDPOINT_NOT_FOUND,
                "endpoint was not found",
            ),
        ) from exc
    if endpoint not in {record.endpoint for record in services.events.endpoints()}:
        raise GatewayApiError(
            404,
            GatewayError(
                GatewayErrorCode.ENDPOINT_NOT_FOUND,
                "endpoint was not found",
            ),
        )
    capabilities = await services.runtime.capabilities(
        endpoint.adapter_id,
        endpoint,
    )
    return {
        "id": endpoint_id,
        "endpoint": endpoint_to_dict(endpoint),
        "capabilities": [capability_to_dict(capability) for capability in capabilities],
    }

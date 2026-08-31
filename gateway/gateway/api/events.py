"""Retained event lookup route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from gateway.core import GatewayError, GatewayErrorCode

from .auth import ApiPrincipal
from .dependencies import get_services, require_scope
from .errors import GatewayApiError
from .serialization import event_to_dict

router = APIRouter(tags=["events"])


@router.get("/v1/events/{event_id}")
async def get_event(
    event_id: str,
    request: Request,
    _principal: Annotated[
        ApiPrincipal,
        Depends(require_scope("events:read")),
    ],
) -> dict[str, object]:
    """Return one event retained in memory.

    Args:
        event_id: Stable Gateway event ID.
        request: Current FastAPI request.
        _principal: Authorized caller.

    Returns:
        Serialized event.

    Raises:
        GatewayApiError: If the event is no longer retained.
    """
    event = get_services(request).events.get(event_id)
    if event is None:
        raise GatewayApiError(
            404,
            GatewayError(
                GatewayErrorCode.EVENT_NOT_FOUND,
                "event was not found",
            ),
        )
    return event_to_dict(event)

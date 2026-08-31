"""Adapter lifecycle and status routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from .auth import ApiPrincipal
from .dependencies import get_services, require_scope
from .serialization import runtime_info_to_dict

router = APIRouter(prefix="/v1/adapters", tags=["adapters"])


@router.get("")
async def list_adapters(
    request: Request,
    _principal: Annotated[
        ApiPrincipal,
        Depends(require_scope("adapters:read")),
    ],
) -> dict[str, object]:
    """List configured adapter runtime state.

    Args:
        request: Current FastAPI request.
        _principal: Authorized caller.

    Returns:
        Adapter state collection.
    """
    services = get_services(request)
    return {
        "adapters": [
            runtime_info_to_dict(info) for info in services.runtime.list_info()
        ]
    }


@router.get("/{adapter_id}")
async def get_adapter(
    adapter_id: str,
    request: Request,
    _principal: Annotated[
        ApiPrincipal,
        Depends(require_scope("adapters:read")),
    ],
) -> dict[str, object]:
    """Return one configured adapter.

    Args:
        adapter_id: Configured adapter identifier.
        request: Current FastAPI request.
        _principal: Authorized caller.

    Returns:
        Adapter runtime state.
    """
    return runtime_info_to_dict(get_services(request).runtime.info(adapter_id))


@router.post("/{adapter_id}/start")
async def start_adapter(
    adapter_id: str,
    request: Request,
    _principal: Annotated[
        ApiPrincipal,
        Depends(require_scope("adapters:manage")),
    ],
) -> dict[str, object]:
    """Start one configured adapter.

    Args:
        adapter_id: Configured adapter identifier.
        request: Current FastAPI request.
        _principal: Authorized caller.

    Returns:
        Resulting adapter state.
    """
    info = await get_services(request).runtime.start(adapter_id)
    return runtime_info_to_dict(info)


@router.post("/{adapter_id}/stop")
async def stop_adapter(
    adapter_id: str,
    request: Request,
    _principal: Annotated[
        ApiPrincipal,
        Depends(require_scope("adapters:manage")),
    ],
) -> dict[str, object]:
    """Stop one configured adapter.

    Args:
        adapter_id: Configured adapter identifier.
        request: Current FastAPI request.
        _principal: Authorized caller.

    Returns:
        Resulting adapter state.
    """
    info = await get_services(request).runtime.stop(adapter_id)
    return runtime_info_to_dict(info)


@router.post("/{adapter_id}/restart")
async def restart_adapter(
    adapter_id: str,
    request: Request,
    _principal: Annotated[
        ApiPrincipal,
        Depends(require_scope("adapters:manage")),
    ],
) -> dict[str, object]:
    """Restart one configured adapter.

    Args:
        adapter_id: Configured adapter identifier.
        request: Current FastAPI request.
        _principal: Authorized caller.

    Returns:
        Resulting adapter state.
    """
    info = await get_services(request).runtime.restart(adapter_id)
    return runtime_info_to_dict(info)

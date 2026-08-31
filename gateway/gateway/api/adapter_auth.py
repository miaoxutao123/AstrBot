"""Generic interactive adapter authentication routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from gateway.core import AdapterAuthInfo

from .auth import ApiPrincipal
from .dependencies import get_services, require_scope

router = APIRouter(prefix="/v1/adapters", tags=["adapter-auth"])


def _serialize(info: AdapterAuthInfo) -> dict[str, object]:
    result: dict[str, object] = {"status": info.status.value}
    if info.challenge is not None:
        result["challenge"] = {
            "qr_uri": info.challenge.qr_uri,
            "media_id": info.challenge.media_id,
            "verification_code": info.challenge.verification_code,
            "instructions": info.challenge.instructions,
        }
    if info.reason is not None:
        result["reason"] = info.reason
    return result


@router.get("/{adapter_id}/auth")
async def get_auth(
    adapter_id: str,
    request: Request,
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:read"))],
) -> dict[str, object]:
    return _serialize(await get_services(request).runtime.auth_info(adapter_id))


@router.post("/{adapter_id}/auth/start")
async def start_auth(
    adapter_id: str,
    request: Request,
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:manage"))],
) -> dict[str, object]:
    return _serialize(await get_services(request).runtime.start_auth(adapter_id))


@router.post("/{adapter_id}/auth/cancel")
async def cancel_auth(
    adapter_id: str,
    request: Request,
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:manage"))],
) -> dict[str, object]:
    return _serialize(await get_services(request).runtime.cancel_auth(adapter_id))

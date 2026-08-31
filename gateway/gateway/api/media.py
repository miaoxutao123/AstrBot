"""Opaque media upload, download, and deletion routes."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response, UploadFile

from .auth import ApiPrincipal
from .dependencies import get_services, require_scope

router = APIRouter(prefix="/v1/media", tags=["media"])


@router.post("")
async def upload_media(
    upload: UploadFile,
    request: Request,
    _principal: Annotated[
        ApiPrincipal,
        Depends(require_scope("media:write")),
    ],
    ttl_seconds: Annotated[float | None, Query(gt=0)] = None,
) -> dict[str, object]:
    """Upload one bounded media object.

    Args:
        upload: Multipart file upload.
        request: Current FastAPI request.
        _principal: Authorized caller.
        ttl_seconds: Optional positive TTL override.

    Returns:
        Opaque media metadata.
    """
    store = get_services(request).media
    data = await upload.read(store.max_upload_size + 1)
    metadata = await store.put(
        data,
        upload.content_type or "application/octet-stream",
        upload.filename or "upload.bin",
        ttl_seconds,
    )
    return {"media": metadata.to_dict()}


@router.get("/{media_id}")
async def download_media(
    media_id: str,
    request: Request,
    _principal: Annotated[
        ApiPrincipal,
        Depends(require_scope("media:read")),
    ],
) -> Response:
    """Download one non-expired media object.

    Args:
        media_id: Opaque media identifier.
        request: Current FastAPI request.
        _principal: Authorized caller.

    Returns:
        Media bytes with safe metadata headers.
    """
    content = await get_services(request).media.get(media_id)
    return Response(
        content.data,
        media_type=content.metadata.mime_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            f"{quote(content.metadata.filename, safe='')}"
        },
    )


@router.delete("/{media_id}", status_code=204)
async def delete_media(
    media_id: str,
    request: Request,
    _principal: Annotated[
        ApiPrincipal,
        Depends(require_scope("media:write")),
    ],
) -> Response:
    """Delete one media object.

    Args:
        media_id: Opaque media identifier.
        request: Current FastAPI request.
        _principal: Authorized caller.

    Returns:
        Empty 204 response. Deletion is idempotent.
    """
    await get_services(request).media.delete(media_id)
    return Response(status_code=204)

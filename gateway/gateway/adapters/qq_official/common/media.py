"""QQ Official media conversion shared by WebSocket and future webhook."""

import base64
import mimetypes
from collections.abc import Mapping

from gateway.media import MediaStore
from gateway.profiles.im import IMSegment

from .api import QQOfficialAPI
from .models import QQOfficialEndpoint


async def inbound_attachment(
    attachment: Mapping[str, object], api: QQOfficialAPI, media: MediaStore
) -> IMSegment:
    url = attachment.get("url")
    if not isinstance(url, str) or not url:
        return IMSegment.raw("qq_official", "attachment", attachment)
    raw, mime_type, filename = await api.download(url, media.max_upload_size)
    content_type = attachment.get("content_type")
    if not mime_type and isinstance(content_type, str):
        mime_type = content_type
    fallback = filename or "qq-attachment"
    metadata = await media.put(
        raw,
        mime_type or mimetypes.guess_type(fallback)[0] or "application/octet-stream",
        fallback,
    )
    normalized = metadata.mime_type.split("/", 1)[0]
    segment_type = normalized if normalized in {"image", "audio", "video"} else "file"
    return IMSegment.media(segment_type, metadata)


async def upload_image(
    endpoint: QQOfficialEndpoint,
    segment: IMSegment,
    api: QQOfficialAPI,
    media: MediaStore,
) -> Mapping[str, object]:
    if endpoint.scene not in {"c2c", "group"}:
        raise ValueError("QQ Official image send is supported only for C2C and group")
    reference = segment.data.get("media")
    if not isinstance(reference, Mapping):
        raise ValueError("invalid QQ Official media segment")
    content = await media.get(str(reference.get("media_id", "")))
    prefix = "users" if endpoint.scene == "c2c" else "groups"
    result = await api.request(
        "POST",
        f"/v2/{prefix}/{endpoint.destination_id}/files",
        {
            "file_type": 1,
            "file_data": base64.b64encode(content.data).decode(),
            "srv_send_msg": False,
        },
    )
    file_info = result.get("file_info")
    if not isinstance(file_info, str) or not file_info:
        raise ValueError("QQ Official media response is missing file_info")
    return {"file_info": file_info}

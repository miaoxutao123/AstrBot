"""Weixin encrypted CDN and Gateway media conversion."""

import base64
import hashlib
import mimetypes
import uuid
from collections.abc import Mapping
from typing import Any

from gateway.media import MediaStore
from gateway.profiles.im import IMSegment

from .client import WeixinClient
from .errors import WeixinRequestError
from .session import integer_value, string_value


async def inbound_media_segment(
    item: Mapping[str, Any], client: WeixinClient, media_store: MediaStore
) -> IMSegment | None:
    """Download and store one supported inbound Weixin media item."""
    item_type = integer_value(item.get("type"))
    names = {
        2: ("image_item", "image", "image.jpg"),
        3: ("voice_item", "audio", "voice.silk"),
        4: ("file_item", "file", "file.bin"),
        5: ("video_item", "video", "video.mp4"),
    }
    selected = names.get(item_type)
    if selected is None:
        return None
    field, segment_type, fallback = selected
    value = item.get(field)
    if not isinstance(value, Mapping):
        return None
    media = value.get("media")
    if not isinstance(media, Mapping):
        return None
    query = string_value(media.get("encrypt_query_param"))
    key = string_value(media.get("aes_key")) or None
    if item_type == 2 and not key:
        raw_key = string_value(value.get("aeskey"))
        if raw_key:
            key = base64.b64encode(bytes.fromhex(raw_key)).decode()
    if not query:
        return None
    content = await client.download(query, key, media_store.max_upload_size)
    filename = string_value(value.get("file_name")) or fallback
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    metadata = await media_store.put(content, mime_type, filename)
    return IMSegment.media(segment_type, metadata)


async def prepare_outbound_media(
    user_id: str,
    segment: IMSegment,
    client: WeixinClient,
    media_store: MediaStore,
    token: str,
) -> dict[str, Any]:
    """Resolve, encrypt, and upload one outbound Gateway media segment."""
    media = segment.data.get("media")
    if not isinstance(media, Mapping):
        raise ValueError("media segment is invalid")
    content = await media_store.get(string_value(media.get("media_id")))
    raw = content.data
    key = uuid.uuid4().bytes
    file_key = uuid.uuid4().hex
    upload_type, item_type, field, size_field = {
        "image": (1, 2, "image_item", "mid_size"),
        "video": (2, 5, "video_item", "video_size"),
        "file": (3, 4, "file_item", "len"),
    }[segment.type]
    padded_size = len(raw) + (16 - len(raw) % 16)
    result = await client.request(
        "POST",
        "ilink/bot/getuploadurl",
        payload={
            "filekey": file_key,
            "media_type": upload_type,
            "to_user_id": user_id,
            "rawsize": len(raw),
            "rawfilemd5": hashlib.md5(raw).hexdigest(),
            "filesize": padded_size,
            "no_need_thumb": True,
            "aeskey": key.hex(),
            "base_info": {"channel_version": "astrbot-gateway"},
        },
        token=token,
    )
    upload_param = string_value(result.get("upload_param"))
    upload_url = string_value(result.get("upload_full_url"))
    if not upload_url and not upload_param:
        raise WeixinRequestError("Weixin upload response is incomplete")
    query = await client.upload(upload_url, upload_param, file_key, key, raw)
    media_payload = {
        "encrypt_query_param": query,
        "aes_key": base64.b64encode(key.hex().encode()).decode(),
        "encrypt_type": 1,
    }
    item_value: dict[str, Any] = {
        "media": media_payload,
        size_field: str(len(raw)) if segment.type == "file" else padded_size,
    }
    if segment.type == "file":
        item_value["file_name"] = content.metadata.filename
    return {"type": item_type, field: item_value}

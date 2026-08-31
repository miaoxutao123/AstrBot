"""Gateway IM command to OneBot v11 action conversion.

This transport-focused rewrite preserves the useful send behavior of AstrBot's
aiocqhttp adapter without retaining MessageChain or agent streaming semantics.
"""

import base64
import json
from collections.abc import Mapping
from typing import Any

from gateway.media import MediaStore
from gateway.profiles.im import IMOutboundMessage, IMSegment


def parse_endpoint(endpoint_id: str) -> tuple[bool, int]:
    """Parse an adapter-owned OneBot endpoint identifier.

    Args:
        endpoint_id: `private:<user>` or `group:<group>[:user:<user>]`.

    Returns:
        Group flag and numeric conversation identifier.

    Raises:
        ValueError: If the endpoint syntax is invalid.
    """
    parts = endpoint_id.split(":")
    if len(parts) == 2 and parts[0] in {"private", "group"} and parts[1].isdigit():
        return parts[0] == "group", int(parts[1])
    if (
        len(parts) == 4
        and parts[0] == "group"
        and parts[1].isdigit()
        and parts[2] == "user"
        and parts[3].isdigit()
    ):
        return True, int(parts[1])
    raise ValueError("OneBot endpoint_id is invalid")


async def convert_outbound_message(
    message: IMOutboundMessage,
    media_store: MediaStore,
) -> list[dict[str, Any]]:
    """Convert a standard outbound IM message to OneBot CQ segments.

    Args:
        message: Validated outbound IM profile.
        media_store: Opaque media store used to resolve media IDs.

    Returns:
        Ordered OneBot message segments.

    Raises:
        ValueError: If a standard segment is unsupported by OneBot.
        MediaStoreError: If a referenced media object is missing.
    """
    converted: list[dict[str, Any]] = []
    if message.reply_to:
        converted.append({"type": "reply", "data": {"id": message.reply_to}})
    for segment in message.segments:
        converted.append(await _convert_segment(segment, media_store))
    return converted


async def _convert_segment(
    segment: IMSegment,
    media_store: MediaStore,
) -> dict[str, Any]:
    if segment.type == "text":
        return {"type": "text", "data": {"text": segment.data["text"]}}
    if segment.type == "mention":
        return {"type": "at", "data": {"qq": segment.data["id"]}}
    if segment.type == "mention_all":
        return {"type": "at", "data": {"qq": "all"}}
    if segment.type == "reply":
        return {"type": "reply", "data": {"id": segment.data["message_id"]}}
    if segment.type in {"image", "audio", "video", "file"}:
        media_value = segment.data["media"]
        if not isinstance(media_value, Mapping):
            raise ValueError("media segment is invalid")
        content = await media_store.get(str(media_value["media_id"]))
        encoded = base64.b64encode(content.data).decode("ascii")
        onebot_type = "record" if segment.type == "audio" else segment.type
        return {
            "type": onebot_type,
            "data": {
                "file": f"base64://{encoded}",
                "name": content.metadata.filename,
            },
        }
    if segment.type == "json":
        value = segment.data.get("value")
        return {
            "type": "json",
            "data": {"data": value if isinstance(value, str) else json.dumps(value)},
        }
    if segment.type == "raw":
        if segment.data.get("platform") != "onebot":
            raise ValueError("raw segment belongs to another platform")
        raw_type = segment.data.get("segment_type")
        raw_data = segment.data.get("data")
        if not isinstance(raw_type, str) or not isinstance(raw_data, Mapping):
            raise ValueError("raw OneBot segment is invalid")
        return {"type": raw_type, "data": dict(raw_data)}
    raise ValueError(f"OneBot does not support segment type: {segment.type}")

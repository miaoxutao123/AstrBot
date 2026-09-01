"""OneBot v11 event to Gateway profile conversion.

This is a protocol-focused rewrite of behavior audited from AstrBot's aiocqhttp
adapter at upstream commit 0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d.
Unknown CQ segments are preserved as `raw` instead of being dropped.
"""

import logging
import time
from collections.abc import Mapping
from typing import Any

from gateway.core import EndpointRef, GatewayEvent, Payload
from gateway.media import MediaStore
from gateway.profiles.im import IMConversation, IMMessage, IMSegment, IMSender

from .client import OneBotClient


def _value(data: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = data.get(name)
        if value is not None and str(value):
            return str(value)
    return None


async def convert_inbound_event(
    adapter_id: str,
    event: Mapping[str, Any],
    client: OneBotClient,
    media_store: MediaStore,
    logger: logging.Logger,
) -> GatewayEvent:
    """Convert a OneBot event into a transport-neutral Gateway event.

    Args:
        adapter_id: Configured OneBot adapter instance identifier.
        event: OneBot event payload.
        client: Client used for file URL lookup and bounded downloads.
        media_store: Opaque Gateway media store.
        logger: Adapter-scoped logger.

    Returns:
        Standard IM event or platform-specific notice/request event.

    Raises:
        ValueError: If required OneBot event fields are invalid.
    """
    post_type = str(event.get("post_type", ""))
    user_id = _value(event, "user_id") or "unknown"
    group_id = _value(event, "group_id")
    endpoint_id = f"group:{group_id}" if group_id else f"private:{user_id}"
    source = EndpointRef("im", "onebot", adapter_id, endpoint_id)
    timestamp_value = event.get("time", time.time())
    timestamp = (
        float(timestamp_value)
        if isinstance(timestamp_value, int | float)
        else time.time()
    )
    self_id = _value(event, "self_id")
    metadata = {
        "platform": "onebot",
        "post_type": post_type,
        "self_id": self_id,
        "sub_type": event.get("sub_type"),
    }
    if post_type != "message":
        if post_type not in {"notice", "request", "meta_event"}:
            raise ValueError("OneBot event post_type is unsupported")
        return GatewayEvent(
            id=(
                f"evt_onebot_{adapter_id}_{post_type}_"
                f"{event.get('time', int(timestamp))}_{event.get('user_id', 'none')}"
            ),
            source=source,
            type=f"onebot.{post_type}",
            payload=Payload(f"onebot.{post_type}.v1", {"event": dict(event)}),
            timestamp=timestamp,
            metadata=metadata,
        )

    message_type = event.get("message_type")
    if message_type == "group":
        if group_id is None:
            raise ValueError("OneBot group message lacks group_id")
        conversation = IMConversation("group", group_id)
    elif message_type == "private":
        conversation = IMConversation("private", user_id)
    else:
        raise ValueError("OneBot message_type is unsupported")
    sender_value = event.get("sender")
    sender = sender_value if isinstance(sender_value, Mapping) else {}
    sender_id = _value(sender, "user_id") or user_id
    display_name = _value(sender, "card", "nickname") or sender_id
    raw_message = event.get("message")
    if not isinstance(raw_message, list):
        raise ValueError("OneBot message must use array post format")

    segments: list[IMSegment] = []
    reply_to: str | None = None
    for raw_segment in raw_message:
        if not isinstance(raw_segment, Mapping):
            segments.append(
                IMSegment.raw("onebot", "invalid", {"value": str(raw_segment)})
            )
            continue
        segment_type = str(raw_segment.get("type", "unknown"))
        raw_data = raw_segment.get("data")
        data = raw_data if isinstance(raw_data, Mapping) else {}
        if segment_type == "text":
            text = data.get("text")
            if isinstance(text, str) and text.strip():
                segments.append(IMSegment.text(text))
            else:
                segments.append(IMSegment.raw("onebot", segment_type, data))
        elif segment_type == "at":
            target = _value(data, "qq")
            if target == "all":
                segments.append(IMSegment("mention_all", {}))
            elif target:
                mention_data: dict[str, Any] = {"id": target}
                display = _value(data, "name")
                if display:
                    mention_data["display_name"] = display
                segments.append(IMSegment("mention", mention_data))
            else:
                segments.append(IMSegment.raw("onebot", segment_type, data))
        elif segment_type == "reply":
            message_id = _value(data, "id")
            if message_id:
                reply_to = message_id
                segments.append(IMSegment("reply", {"message_id": message_id}))
            else:
                segments.append(IMSegment.raw("onebot", segment_type, data))
        elif segment_type in {"image", "record", "video", "file"}:
            url = _value(data, "url")
            if url is None and segment_type == "file":
                file_id = _value(data, "file_id", "file")
                if file_id:
                    action = (
                        "get_group_file_url" if group_id else "get_private_file_url"
                    )
                    params: dict[str, Any] = {"file_id": file_id}
                    if group_id:
                        params["group_id"] = int(group_id)
                    try:
                        result = await client.call_action(action, **params)
                        url = _value(result, "url")
                    except Exception:
                        logger.warning(
                            "onebot_media_url_lookup_failed",
                            extra={"adapter_id": adapter_id},
                        )
            if url:
                try:
                    content, mime_type, downloaded_name = await client.download(
                        url,
                        media_store.max_upload_size,
                    )
                    filename = (
                        _value(data, "file_name", "name", "file") or downloaded_name
                    )
                    stored = await media_store.put(content, mime_type, filename)
                    profile_type = "audio" if segment_type == "record" else segment_type
                    segments.append(IMSegment.media(profile_type, stored))
                    continue
                except Exception:
                    logger.warning(
                        "onebot_media_ingest_failed",
                        extra={"adapter_id": adapter_id},
                    )
            segments.append(IMSegment.raw("onebot", segment_type, data))
        elif segment_type == "json":
            segments.append(IMSegment("json", {"value": data.get("data")}))
        elif (
            segment_type == "location"
            and isinstance(data.get("lat"), int | float)
            and isinstance(data.get("lon"), int | float)
        ):
            segments.append(
                IMSegment(
                    "location",
                    {
                        "latitude": data["lat"],
                        "longitude": data["lon"],
                        "title": data.get("title"),
                        "content": data.get("content"),
                    },
                )
            )
        else:
            segments.append(IMSegment.raw("onebot", segment_type, data))
    if not segments:
        segments.append(IMSegment.raw("onebot", "empty", {"message": []}))
    message_id = _value(event, "message_id")
    if message_id is None:
        raise ValueError("OneBot message lacks message_id")
    profile = IMMessage(
        message_id=message_id,
        conversation=conversation,
        sender=IMSender(sender_id, display_name),
        segments=tuple(segments),
        reply_to=reply_to,
    )
    return GatewayEvent(
        id=f"evt_onebot_{adapter_id}_{message_id}",
        source=source,
        type="im.message",
        payload=profile.to_payload(),
        timestamp=timestamp,
        metadata=metadata,
    )

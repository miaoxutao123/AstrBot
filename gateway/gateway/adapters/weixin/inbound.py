"""Weixin inbound message to Gateway IM conversion."""

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from gateway.core import EndpointRef, GatewayEvent
from gateway.media import MediaStore
from gateway.profiles.im import IMConversation, IMMessage, IMSegment, IMSender

from .client import WeixinClient
from .media import inbound_media_segment
from .session import integer_value, string_value


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """Converted event plus credential state learned from the message."""

    event: GatewayEvent
    user_id: str
    context_token: str | None


async def convert_inbound_message(
    instance_id: str,
    raw: Mapping[str, Any],
    client: WeixinClient,
    media_store: MediaStore,
) -> InboundMessage | None:
    """Convert one Weixin update while preserving unknown content as raw."""
    sender = string_value(raw.get("from_user_id"))
    if not sender:
        return None
    segments: list[IMSegment] = []
    reply_to: str | None = None
    items = raw.get("item_list", [])
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            if integer_value(item.get("type")) == 1:
                text_item = item.get("text_item")
                text = (
                    string_value(text_item.get("text"))
                    if isinstance(text_item, Mapping)
                    else ""
                )
                if text:
                    segments.append(IMSegment.text(text))
            else:
                media_segment = await inbound_media_segment(item, client, media_store)
                if media_segment is not None:
                    segments.append(media_segment)
            ref = item.get("ref_msg")
            if isinstance(ref, Mapping):
                referenced = ref.get("message_item")
                if isinstance(referenced, Mapping):
                    reply_to = string_value(
                        referenced.get("message_id") or referenced.get("msg_id")
                    )
                    reference_time = string_value(referenced.get("create_time_ms"))
                    if not reply_to and reference_time:
                        reply_to = f"weixin_ref_{reference_time}"
    if not segments:
        segments.append(IMSegment.raw("weixin", "message", raw))
    message_id = (
        string_value(raw.get("message_id") or raw.get("msg_id")) or uuid.uuid4().hex
    )
    timestamp_value = raw.get("create_time_ms") or raw.get("create_time") or time.time()
    timestamp = (
        float(timestamp_value) / 1000
        if isinstance(timestamp_value, int | float)
        and timestamp_value > 1_000_000_000_000
        else float(timestamp_value)
    )
    profile = IMMessage(
        message_id,
        IMConversation("private", sender),
        IMSender(sender, sender),
        tuple(segments),
        reply_to,
    )
    event = GatewayEvent(
        id=f"evt_weixin_{instance_id}_{message_id}",
        source=EndpointRef("im", "weixin", instance_id, sender),
        type="im.message.received",
        payload=profile.to_payload(),
        timestamp=timestamp,
        metadata={"platform": "weixin"},
    )
    return InboundMessage(event, sender, string_value(raw.get("context_token")) or None)

"""Normalized QQ Official event to Gateway IM conversion."""

import time
from collections.abc import Mapping
from typing import Any

from gateway.core import EndpointRef, GatewayEvent
from gateway.media import MediaStore
from gateway.profiles.im import IMConversation, IMMessage, IMSegment, IMSender

from .api import QQOfficialAPI
from .media import inbound_attachment
from .models import normalize_message


async def convert_event(
    instance_id: str,
    event_type: str,
    data: Mapping[str, Any],
    api: QQOfficialAPI,
    media: MediaStore,
) -> GatewayEvent | None:
    message = normalize_message(event_type, data)
    if message is None:
        return None
    segments: list[IMSegment] = []
    if message.content:
        segments.append(IMSegment.text(message.content))
    for attachment in message.attachments:
        segments.append(await inbound_attachment(attachment, api, media))
    elements = data.get("msg_elements")
    if isinstance(elements, list):
        for element in elements:
            if isinstance(element, Mapping) and element.get("type") not in {
                None,
                "text",
                1,
            }:
                segments.append(IMSegment.raw("qq_official", "msg_element", element))
    if not segments:
        segments.append(IMSegment.raw("qq_official", event_type, data))
    profile = IMMessage(
        message.message_id,
        IMConversation(message.conversation_type, message.endpoint.destination_id),
        IMSender(message.sender_id, message.sender_name),
        tuple(segments),
        message.reply_to,
    )
    return GatewayEvent(
        id=f"evt_qq_official_{instance_id}_{message.message_id}",
        source=EndpointRef("im", "qq_official", instance_id, message.endpoint.encode()),
        type="im.message.received",
        payload=profile.to_payload(),
        timestamp=message.timestamp or time.time(),
        metadata=dict(message.metadata),
    )

"""Satori event and XML element conversion."""

import mimetypes
import time
import uuid
from collections.abc import Mapping
from typing import Any
from xml.etree import ElementTree

from gateway.core import EndpointRef, GatewayEvent
from gateway.media import MediaStore
from gateway.profiles.im import IMConversation, IMMessage, IMSegment, IMSender

from .client import SatoriClient
from .protocol import SatoriLogin, endpoint_id


async def _segments(
    content: str, client: SatoriClient, media: MediaStore
) -> tuple[IMSegment, ...]:
    if not content:
        return (IMSegment.raw("satori", "empty", {}),)
    try:
        root = ElementTree.fromstring(f"<root>{content}</root>")
    except ElementTree.ParseError:
        return (IMSegment.raw("satori", "malformed", {"content": content}),)
    result: list[IMSegment] = []
    if root.text and root.text.strip():
        result.append(IMSegment.text(root.text))
    for child in root:
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag == "at" and (target := child.get("id") or child.get("name")):
            result.append(IMSegment("mention", {"id": target}))
        elif tag in {"quote", "reply"} and child.get("id"):
            result.append(IMSegment("reply", {"message_id": child.get("id")}))
        elif tag in {"img", "image", "audio", "video", "file"} and child.get("src"):
            raw, mime_type, filename = await client.download(
                child.get("src", ""), media.max_upload_size
            )
            fallback = child.get("name") or f"satori-{tag}"
            metadata = await media.put(
                raw,
                mime_type
                or mimetypes.guess_type(fallback)[0]
                or "application/octet-stream",
                filename or fallback,
            )
            segment_type = "image" if tag in {"img", "image"} else tag
            result.append(IMSegment.media(segment_type, metadata))
        else:
            result.append(
                IMSegment.raw(
                    "satori",
                    tag,
                    {"attributes": dict(child.attrib), "text": child.text or ""},
                )
            )
        if child.tail and child.tail.strip():
            result.append(IMSegment.text(child.tail))
    return tuple(result) or (IMSegment.raw("satori", "content", {"content": content}),)


async def convert_event(
    instance_id: str, event: Mapping[str, Any], client: SatoriClient, media: MediaStore
) -> GatewayEvent | None:
    if event.get("type") != "message-created":
        return None
    message = event.get("message")
    user = event.get("user")
    channel = event.get("channel")
    login_value = event.get("login")
    if not all(
        isinstance(value, Mapping) for value in (message, user, channel, login_value)
    ):
        return None
    assert (
        isinstance(message, Mapping)
        and isinstance(user, Mapping)
        and isinstance(channel, Mapping)
        and isinstance(login_value, Mapping)
    )
    login = SatoriLogin.from_mapping(login_value)
    sender = user.get("id")
    channel_id = channel.get("id")
    if (
        login is None
        or not isinstance(sender, str)
        or not sender
        or not isinstance(channel_id, str)
        or not channel_id
        or sender == login.self_id
    ):
        return None
    raw_message_id = message.get("id")
    message_id = raw_message_id if isinstance(raw_message_id, str) else uuid.uuid4().hex
    raw_content = message.get("content")
    content = raw_content if isinstance(raw_content, str) else ""
    segments = await _segments(content, client, media)
    reply_to = None
    quote_value = message.get("quote")
    if isinstance(quote_value, Mapping) and isinstance(quote_value.get("id"), str):
        reply_to = quote_value["id"]
    if reply_to is None:
        reply_to = next(
            (
                str(segment.data["message_id"])
                for segment in segments
                if segment.type == "reply"
            ),
            None,
        )
    guild = event.get("guild")
    guild_id = guild.get("id") if isinstance(guild, Mapping) else None
    conversation = IMConversation("channel" if guild_id else "private", channel_id)
    profile = IMMessage(
        message_id,
        conversation,
        IMSender(sender, str(user.get("nick") or user.get("name") or sender)),
        segments,
        reply_to,
    )
    timestamp = event.get("timestamp", time.time())
    return GatewayEvent(
        id=f"evt_satori_{instance_id}_{message_id}",
        source=EndpointRef("im", "satori", instance_id, endpoint_id(login, channel_id)),
        type="im.message.received",
        payload=profile.to_payload(),
        timestamp=float(timestamp) / 1000
        if isinstance(timestamp, int | float) and timestamp > 1_000_000_000_000
        else float(timestamp),
        metadata={
            "satori_platform": login.platform,
            "satori_self_id": login.self_id,
            "satori_guild_id": guild_id,
        },
    )

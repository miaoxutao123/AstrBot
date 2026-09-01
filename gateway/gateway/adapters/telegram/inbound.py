"""Telegram Bot API update to Gateway IM profile conversion.

This protocol-focused rewrite is informed by AstrBot's Telegram message conversion
at upstream commit 0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d. Unknown data is
preserved as `raw` rather than silently discarded.
"""

import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any

from gateway.core import EndpointRef, GatewayEvent, Payload
from gateway.media import MediaStore
from gateway.profiles.im import IMConversation, IMMessage, IMSegment, IMSender

from .client import TelegramClient


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _value(data: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = data.get(name)
        if value is not None and str(value):
            return str(value)
    return None


def _message_update(
    update: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, str]:
    for field, event_type in (
        ("message", "im.message"),
        ("channel_post", "im.message"),
        ("edited_message", "im.message.edited"),
        ("edited_channel_post", "im.message.edited"),
    ):
        value = update.get(field)
        if isinstance(value, Mapping):
            return value, event_type
    return None, "telegram.update"


def telegram_endpoint(message: Mapping[str, Any]) -> tuple[str, str, str]:
    """Map Telegram chat/thread fields to adapter-owned addressing.

    Args:
        message: Normalized Telegram message.

    Returns:
        Endpoint ID, conversation type, and conversation ID.

    Raises:
        ValueError: If the message lacks a valid chat.
    """
    chat = _mapping(message.get("chat"))
    chat_id = _value(chat, "id")
    if chat_id is None:
        raise ValueError("Telegram message lacks chat id")
    chat_type = str(chat.get("type", "unknown"))
    thread_id = _value(message, "message_thread_id")
    if thread_id is not None:
        return f"thread:{chat_id}:{thread_id}", "thread", f"{chat_id}:{thread_id}"
    if chat_type == "private":
        return f"private:{chat_id}", "private", chat_id
    if chat_type == "channel":
        return f"channel:{chat_id}", "channel", chat_id
    return f"group:{chat_id}", "group", chat_id


def _utf16_slice(text: str, offset: int, length: int) -> tuple[int, int, str]:
    encoded = text.encode("utf-16-le")
    start_bytes = max(offset, 0) * 2
    end_bytes = max(offset + length, 0) * 2
    prefix = encoded[:start_bytes].decode("utf-16-le")
    value = encoded[start_bytes:end_bytes].decode("utf-16-le")
    return len(prefix), len(prefix) + len(value), value


def _text_segments(
    text: str,
    entities_value: object,
) -> list[IMSegment]:
    entities = entities_value if isinstance(entities_value, Sequence) else []
    mentions: list[tuple[int, int, str, str]] = []
    for raw_entity in entities:
        entity = _mapping(raw_entity)
        if entity.get("type") not in {"mention", "text_mention"}:
            continue
        offset = entity.get("offset")
        length = entity.get("length")
        if not isinstance(offset, int) or not isinstance(length, int):
            continue
        try:
            start, end, display = _utf16_slice(text, offset, length)
        except UnicodeError:
            continue
        user = _mapping(entity.get("user"))
        target = _value(user, "id")
        if target is None and display.startswith("@"):
            target = display[1:]
        if target:
            mentions.append((start, end, target, display))
    if not mentions:
        return [IMSegment.text(text)] if text.strip() else []
    segments: list[IMSegment] = []
    cursor = 0
    for start, end, target, display in sorted(mentions):
        if start < cursor:
            continue
        if text[cursor:start]:
            segments.append(IMSegment.text(text[cursor:start]))
        data: dict[str, Any] = {"id": target}
        if display:
            data["display_name"] = display
        segments.append(IMSegment("mention", data))
        cursor = end
    if text[cursor:]:
        segments.append(IMSegment.text(text[cursor:]))
    return segments


def _safe_filename(value: str) -> str:
    sanitized = "".join(
        "_" if character in {"/", "\\", "\x00", "\r", "\n", '"'} else character
        for character in value
    ).strip()
    return sanitized or "telegram-media.bin"


async def _media_segment(
    message: Mapping[str, Any],
    client: TelegramClient,
    media_store: MediaStore,
    logger: logging.Logger,
) -> IMSegment | None:
    descriptor: Mapping[str, Any] = {}
    segment_type = ""
    default_name = "telegram-media.bin"
    photos = message.get("photo")
    if isinstance(photos, Sequence) and photos:
        descriptor = _mapping(photos[-1])
        segment_type = "image"
        default_name = "telegram-photo.jpg"
    else:
        for field, profile_type, fallback in (
            ("voice", "audio", "telegram-voice.ogg"),
            ("audio", "audio", "telegram-audio.bin"),
            ("video", "video", "telegram-video.mp4"),
            ("video_note", "video", "telegram-video-note.mp4"),
            ("document", "file", "telegram-document.bin"),
            ("sticker", "image", "telegram-sticker.webp"),
        ):
            value = message.get(field)
            if isinstance(value, Mapping):
                descriptor = value
                segment_type = profile_type
                default_name = fallback
                break
    if not descriptor:
        return None
    file_id = _value(descriptor, "file_id")
    if file_id is None:
        return IMSegment.raw("telegram", "media", descriptor)
    declared_size = descriptor.get("file_size")
    if isinstance(declared_size, int) and declared_size > media_store.max_upload_size:
        return IMSegment.raw("telegram", "media_too_large", descriptor)
    try:
        content, inferred_mime, inferred_name = await client.download(
            file_id,
            media_store.max_upload_size,
        )
        mime_type = _value(descriptor, "mime_type") or inferred_mime
        filename = _safe_filename(
            _value(descriptor, "file_name") or inferred_name or default_name
        )
        metadata = await media_store.put(content, mime_type, filename)
        return IMSegment.media(segment_type, metadata)
    except Exception:
        logger.warning("telegram_media_ingest_failed")
        return IMSegment.raw("telegram", "media", descriptor)


async def convert_inbound_update(
    adapter_id: str,
    update: Mapping[str, Any],
    client: TelegramClient,
    media_store: MediaStore,
    logger: logging.Logger,
) -> GatewayEvent:
    """Convert a normalized Telegram update into a Gateway event.

    Args:
        adapter_id: Configured Telegram adapter instance.
        update: Telegram Bot API update mapping.
        client: Client used for file downloads.
        media_store: Opaque Gateway media store.
        logger: Adapter-scoped logger.

    Returns:
        Standard IM event or a lossless Telegram platform event.
    """
    update_id = _value(update, "update_id") or str(int(time.time() * 1000))
    message, event_type = _message_update(update)
    if message is None:
        reaction = _mapping(update.get("message_reaction"))
        if reaction:
            chat = _mapping(reaction.get("chat"))
            chat_id = _value(chat, "id") or "unknown"
            chat_type = str(chat.get("type", "unknown"))
            prefix = {"private": "private", "channel": "channel"}.get(
                chat_type, "group"
            )
            source = EndpointRef("im", "telegram", adapter_id, f"{prefix}:{chat_id}")
            return GatewayEvent(
                id=f"evt_telegram_{adapter_id}_{update_id}",
                source=source,
                type="im.reaction",
                payload=Payload(
                    "im.reaction.event.v1",
                    {
                        "message_id": _value(reaction, "message_id") or "unknown",
                        "old_reaction": reaction.get("old_reaction", []),
                        "new_reaction": reaction.get("new_reaction", []),
                        "user": reaction.get("user"),
                    },
                ),
                timestamp=float(reaction.get("date", time.time())),
                metadata={"platform": "telegram", "update_id": update_id},
            )
        return GatewayEvent(
            id=f"evt_telegram_{adapter_id}_{update_id}",
            source=EndpointRef("im", "telegram", adapter_id, "telegram:updates"),
            type="telegram.update",
            payload=Payload("telegram.update.v1", {"update": dict(update)}),
            metadata={"platform": "telegram", "update_id": update_id},
        )

    endpoint_id, conversation_type, conversation_id = telegram_endpoint(message)
    chat = _mapping(message.get("chat"))
    sender = _mapping(message.get("from") or message.get("from_user"))
    if not sender:
        sender = _mapping(message.get("sender_chat")) or chat
    sender_id = _value(sender, "id") or "unknown"
    display_name = (
        _value(sender, "username", "title")
        or " ".join(
            part
            for part in (
                _value(sender, "first_name"),
                _value(sender, "last_name"),
            )
            if part
        )
        or sender_id
    )
    segments: list[IMSegment] = []
    reply = _mapping(message.get("reply_to_message"))
    reply_to = _value(reply, "message_id") if reply else None
    if reply_to:
        segments.append(IMSegment("reply", {"message_id": reply_to}))
    media = await _media_segment(message, client, media_store, logger)
    if media is not None:
        segments.append(media)
    text = message.get("text")
    if isinstance(text, str):
        segments.extend(_text_segments(text, message.get("entities")))
    caption = message.get("caption")
    if isinstance(caption, str):
        segments.extend(_text_segments(caption, message.get("caption_entities")))
    location = _mapping(message.get("location"))
    if isinstance(location.get("latitude"), int | float) and isinstance(
        location.get("longitude"), int | float
    ):
        segments.append(
            IMSegment(
                "location",
                {
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                },
            )
        )
    if not segments:
        segments.append(IMSegment.raw("telegram", "message", message))
    message_id = _value(message, "message_id")
    if message_id is None:
        raise ValueError("Telegram message lacks message_id")
    profile = IMMessage(
        message_id=message_id,
        conversation=IMConversation(conversation_type, conversation_id),
        sender=IMSender(sender_id, display_name),
        segments=tuple(segments),
        reply_to=reply_to,
    )
    timestamp_value = message.get("date", time.time())
    timestamp = (
        float(timestamp_value)
        if isinstance(timestamp_value, int | float)
        else time.time()
    )
    return GatewayEvent(
        id=f"evt_telegram_{adapter_id}_{update_id}",
        source=EndpointRef("im", "telegram", adapter_id, endpoint_id),
        type=event_type,
        payload=profile.to_payload(),
        timestamp=timestamp,
        metadata={
            "platform": "telegram",
            "update_id": update_id,
            "chat_type": chat.get("type"),
            "media_group_id": message.get("media_group_id"),
        },
    )

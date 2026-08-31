"""Gateway IM command to Telegram Bot API conversion.

The transport behavior is a focused rewrite of message-length, media, reply,
reaction, edit, delete, and typing logic audited from AstrBot's Telegram adapter.
No Agent streaming or MessageChain behavior is retained.
"""

from typing import Any

from gateway.media import MediaStore
from gateway.profiles.im import (
    IMMessageEdit,
    IMOutboundMessage,
    IMReaction,
    IMSegment,
    IMTyping,
)

from .client import TelegramClient, TelegramUpload

MAX_TEXT_LENGTH = 4096
_TYPING_ACTIONS = {
    "typing",
    "upload_photo",
    "record_voice",
    "upload_video",
    "upload_document",
}


def parse_endpoint(endpoint_id: str) -> tuple[int, int | None]:
    """Parse an adapter-owned Telegram endpoint identifier.

    Args:
        endpoint_id: Private/group/channel or thread endpoint.

    Returns:
        Numeric chat ID and optional thread ID.

    Raises:
        ValueError: If endpoint syntax is invalid.
    """
    parts = endpoint_id.split(":")
    if len(parts) == 2 and parts[0] in {"private", "group", "channel"}:
        try:
            return int(parts[1]), None
        except ValueError as exc:
            raise ValueError("Telegram endpoint chat ID is invalid") from exc
    if len(parts) == 3 and parts[0] == "thread":
        try:
            return int(parts[1]), int(parts[2])
        except ValueError as exc:
            raise ValueError("Telegram thread endpoint is invalid") from exc
    raise ValueError("Telegram endpoint_id is invalid")


def split_text(text: str) -> list[str]:
    """Split text at readable boundaries within Telegram's limit.

    Args:
        text: Non-empty plain text.

    Returns:
        Ordered chunks no longer than 4096 characters.
    """
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= MAX_TEXT_LENGTH:
            chunks.append(remaining)
            break
        candidate = remaining[:MAX_TEXT_LENGTH]
        split_at = max(
            candidate.rfind("\n\n"),
            candidate.rfind("\n"),
            candidate.rfind(". "),
            candidate.rfind(" "),
        )
        if split_at < MAX_TEXT_LENGTH // 2:
            split_at = MAX_TEXT_LENGTH
        else:
            split_at += 1
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    return chunks


def text_from_segments(segments: tuple[IMSegment, ...]) -> str:
    """Render Telegram-editable text and mention segments.

    Args:
        segments: Standard IM segments.

    Returns:
        Plain Telegram text.

    Raises:
        ValueError: If a segment cannot be represented by a text edit.
    """
    pieces: list[str] = []
    for segment in segments:
        if segment.type == "text":
            pieces.append(str(segment.data["text"]))
        elif segment.type == "mention":
            name = str(segment.data.get("display_name") or segment.data["id"])
            pieces.append(name if name.startswith("@") else f"@{name}")
        else:
            raise ValueError(f"Telegram text operation does not support {segment.type}")
    text = "".join(pieces)
    if not text:
        raise ValueError("Telegram text must not be empty")
    return text


def _routing(chat_id: int, thread_id: int | None) -> dict[str, Any]:
    params: dict[str, Any] = {"chat_id": chat_id}
    if thread_id is not None:
        params["message_thread_id"] = thread_id
    return params


async def send_outbound_message(
    client: TelegramClient,
    endpoint_id: str,
    message: IMOutboundMessage,
    media_store: MediaStore,
) -> str | None:
    """Send standard IM segments through Telegram methods.

    Args:
        client: Telegram transport client.
        endpoint_id: Adapter-owned destination.
        message: Standard outbound message.
        media_store: Opaque media store.

    Returns:
        First Telegram message ID, when returned.
    """
    chat_id, thread_id = parse_endpoint(endpoint_id)
    reply_to = message.reply_to or next(
        (
            str(segment.data["message_id"])
            for segment in message.segments
            if segment.type == "reply"
        ),
        None,
    )
    text_buffer: list[IMSegment] = []
    external_ids: list[str] = []
    first_call = True

    async def call(method: str, **params: Any) -> None:
        nonlocal first_call
        payload = _routing(chat_id, thread_id)
        if reply_to is not None and first_call:
            payload["reply_to_message_id"] = int(reply_to)
        payload.update(params)
        result = await client.call(method, **payload)
        message_id = result.get("message_id")
        if message_id is not None:
            external_ids.append(str(message_id))
        first_call = False

    async def flush_text() -> None:
        if not text_buffer:
            return
        text = text_from_segments(tuple(text_buffer))
        text_buffer.clear()
        for chunk in split_text(text):
            await call("send_message", text=chunk)

    for segment in message.segments:
        if segment.type in {"text", "mention"}:
            text_buffer.append(segment)
            continue
        if segment.type == "reply":
            continue
        await flush_text()
        if segment.type in {"image", "audio", "video", "file"}:
            media = segment.data["media"]
            content = await media_store.get(str(media["media_id"]))
            method = {
                "image": "send_photo",
                "audio": "send_voice",
                "video": "send_video",
                "file": "send_document",
            }[segment.type]
            await call(
                method,
                _upload=TelegramUpload(content.data, content.metadata.filename),
            )
        elif segment.type == "location":
            await call(
                "send_location",
                latitude=segment.data["latitude"],
                longitude=segment.data["longitude"],
            )
        else:
            raise ValueError(f"Telegram does not support segment type: {segment.type}")
    await flush_text()
    return external_ids[0] if external_ids else None


async def edit_message(
    client: TelegramClient,
    endpoint_id: str,
    edit: IMMessageEdit,
) -> None:
    """Edit one Telegram text message.

    Args:
        client: Telegram transport client.
        endpoint_id: Adapter-owned destination.
        edit: Standard edit operation.
    """
    chat_id, _thread_id = parse_endpoint(endpoint_id)
    text = text_from_segments(edit.segments)
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError("Telegram edited text exceeds 4096 characters")
    await client.call(
        "edit_message_text",
        chat_id=chat_id,
        message_id=int(edit.message_id),
        text=text,
    )


async def set_reaction(
    client: TelegramClient,
    endpoint_id: str,
    reaction: IMReaction,
    *,
    remove: bool,
) -> None:
    """Add or remove the bot's Telegram reaction.

    Args:
        client: Telegram transport client.
        endpoint_id: Adapter-owned destination.
        reaction: Standard reaction operation.
        remove: Whether to clear the bot reaction.
    """
    chat_id, _thread_id = parse_endpoint(endpoint_id)
    if not remove and reaction.emoji is None:
        raise ValueError("reaction add requires emoji")
    await client.call(
        "set_message_reaction",
        chat_id=chat_id,
        message_id=int(reaction.message_id),
        _reaction=None if remove else reaction.emoji,
        is_big=reaction.big,
    )


async def send_typing(
    client: TelegramClient,
    endpoint_id: str,
    typing: IMTyping,
) -> None:
    """Send one Telegram chat action.

    Args:
        client: Telegram transport client.
        endpoint_id: Adapter-owned destination.
        typing: Standard typing operation.
    """
    if typing.action not in _TYPING_ACTIONS:
        raise ValueError("Telegram typing action is unsupported")
    chat_id, thread_id = parse_endpoint(endpoint_id)
    await client.call(
        "send_chat_action",
        **_routing(chat_id, thread_id),
        action=typing.action,
    )

"""Telegram fixture, media, and outbound conversion tests."""

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from gateway.adapters.telegram.inbound import convert_inbound_update
from gateway.adapters.telegram.outbound import send_outbound_message, split_text
from gateway.media import MemoryMediaStore
from gateway.profiles.im import IMMessage, IMOutboundMessage, IMSegment
from tests.adapters.telegram.fakes import FakeTelegramClient

FIXTURES = Path(__file__).parents[2] / "fixtures" / "telegram"


def fixture(name: str) -> dict[str, Any]:
    loaded = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError("Telegram fixture must be an object")
    return dict(loaded)


@pytest.mark.asyncio
async def test_private_text_uses_utf16_mentions() -> None:
    event = await convert_inbound_update(
        "telegram-main",
        fixture("private_text.json"),
        FakeTelegramClient(),
        MemoryMediaStore(),
        logging.getLogger("test.telegram"),
    )

    profile = IMMessage.from_payload(event.payload)
    assert event.source.endpoint_id == "private:12345"
    assert profile.conversation.type == "private"
    assert [segment.type for segment in profile.segments] == ["text", "mention"]
    assert profile.segments[0].data["text"] == "Hi 😀 "
    assert profile.segments[1].data["id"] == "alice"


@pytest.mark.asyncio
async def test_group_thread_reply_mapping() -> None:
    event = await convert_inbound_update(
        "telegram-main",
        fixture("group_reply.json"),
        FakeTelegramClient(),
        MemoryMediaStore(),
        logging.getLogger("test.telegram"),
    )

    profile = IMMessage.from_payload(event.payload)
    assert event.source.endpoint_id == "thread:-100123:9"
    assert profile.conversation.type == "thread"
    assert profile.reply_to == "49"
    assert [segment.type for segment in profile.segments] == ["reply", "text"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "descriptor", "expected"),
    [
        ("photo", [{"file_id": "photo-file", "file_size": 5}], "image"),
        (
            "voice",
            {"file_id": "audio-file", "mime_type": "audio/ogg"},
            "audio",
        ),
        (
            "video",
            {"file_id": "video-file", "mime_type": "video/mp4"},
            "video",
        ),
        (
            "document",
            {
                "file_id": "document-file",
                "file_name": "report.txt",
                "mime_type": "text/plain",
            },
            "file",
        ),
    ],
)
async def test_image_and_file_enter_media_store(
    field: str,
    descriptor: object,
    expected: str,
) -> None:
    update = fixture("private_text.json")
    message = update["message"]
    message.pop("text")
    message.pop("entities")
    message[field] = descriptor
    store = MemoryMediaStore()

    event = await convert_inbound_update(
        "telegram-main",
        update,
        FakeTelegramClient(),
        store,
        logging.getLogger("test.telegram"),
    )

    segment = IMMessage.from_payload(event.payload).segments[0]
    assert segment.type == expected
    assert (await store.get(segment.data["media"]["media_id"])).data


@pytest.mark.asyncio
async def test_channel_edit_and_reaction_updates_remain_observable() -> None:
    client = FakeTelegramClient()
    store = MemoryMediaStore()
    edited = {
        "update_id": 2001,
        "edited_channel_post": {
            "message_id": 80,
            "date": 1788160002,
            "chat": {"id": -100999, "type": "channel", "title": "News"},
            "sender_chat": {"id": -100999, "title": "News"},
            "text": "updated",
        },
    }
    reaction = {
        "update_id": 2002,
        "message_reaction": {
            "chat": {"id": -100999, "type": "channel"},
            "message_id": 80,
            "date": 1788160003,
            "old_reaction": [],
            "new_reaction": [{"type": "emoji", "emoji": "👍"}],
        },
    }

    edit_event = await convert_inbound_update(
        "telegram-main", edited, client, store, logging.getLogger("test.telegram")
    )
    reaction_event = await convert_inbound_update(
        "telegram-main", reaction, client, store, logging.getLogger("test.telegram")
    )

    assert edit_event.source.endpoint_id == "channel:-100999"
    assert edit_event.type == "im.message.edited"
    assert IMMessage.from_payload(edit_event.payload).conversation.type == "channel"
    assert reaction_event.type == "im.reaction"
    assert reaction_event.source.endpoint_id == "channel:-100999"
    assert reaction_event.payload.data["new_reaction"][0]["emoji"] == "👍"


@pytest.mark.asyncio
async def test_outbound_splits_text_and_sends_media_reply() -> None:
    client = FakeTelegramClient()
    store = MemoryMediaStore()
    image = await store.put(b"photo", "image/jpeg", "photo.jpg")
    message = IMOutboundMessage(
        segments=(
            IMSegment.text("a" * 5000),
            IMSegment.media("image", image),
        ),
        reply_to="49",
    )

    external_id = await send_outbound_message(
        client,
        "thread:-100123:9",
        message,
        store,
    )

    assert external_id == "701"
    assert [method for method, _params in client.calls] == [
        "send_message",
        "send_message",
        "send_photo",
    ]
    assert all(
        len(params["text"]) <= 4096
        for method, params in client.calls
        if method == "send_message"
    )
    assert client.calls[0][1]["reply_to_message_id"] == 49
    assert "reply_to_message_id" not in client.calls[1][1]
    assert client.calls[2][1]["message_thread_id"] == 9
    assert [len(chunk) for chunk in split_text("x" * 5000)] == [4096, 904]

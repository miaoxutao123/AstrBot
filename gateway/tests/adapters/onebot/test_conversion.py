"""OneBot protocol fixture and outbound conversion tests."""

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from gateway.adapters.onebot.inbound import convert_inbound_event
from gateway.adapters.onebot.outbound import convert_outbound_message
from gateway.media import MemoryMediaStore
from gateway.profiles.im import IMMessage, IMOutboundMessage, IMSegment
from tests.adapters.onebot.fakes import FakeOneBotClient

FIXTURES = Path(__file__).parents[2] / "fixtures" / "onebot"


def fixture(name: str) -> dict[str, Any]:
    """Load one protocol fixture.

    Args:
        name: Fixture filename.

    Returns:
        Parsed OneBot payload.
    """
    loaded = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError("OneBot fixture must be an object")
    return dict(loaded)


@pytest.mark.asyncio
async def test_private_text_fixture_becomes_standard_im_message() -> None:
    event = await convert_inbound_event(
        "qq-main",
        fixture("private_text.json"),
        FakeOneBotClient(),
        MemoryMediaStore(),
        logging.getLogger("test.onebot"),
    )

    profile = IMMessage.from_payload(event.payload)
    assert event.id == "evt_onebot_qq-main_101"
    assert event.source.endpoint_id == "private:20001"
    assert profile.conversation.type == "private"
    assert profile.sender.display_name == "Alice"
    assert profile.segments == (IMSegment.text("hello"),)


@pytest.mark.asyncio
async def test_group_fixture_preserves_mentions_reply_media_file_and_unknown() -> None:
    client = FakeOneBotClient()
    store = MemoryMediaStore()

    event = await convert_inbound_event(
        "qq-main",
        fixture("group_rich.json"),
        client,
        store,
        logging.getLogger("test.onebot"),
    )

    profile = IMMessage.from_payload(event.payload)
    types = [segment.type for segment in profile.segments]
    assert event.source.endpoint_id == "group:30001"
    assert profile.conversation.type == "group"
    assert profile.reply_to == "99"
    assert types == [
        "reply",
        "mention",
        "mention_all",
        "text",
        "image",
        "file",
        "raw",
    ]
    assert profile.segments[-1].data["segment_type"] == "mface"
    assert client.actions[0][0] == "get_group_file_url"
    image_id = profile.segments[4].data["media"]["media_id"]
    file_id = profile.segments[5].data["media"]["media_id"]
    assert (await store.get(image_id)).data == b"image"
    assert (await store.get(file_id)).data == b"report"


@pytest.mark.asyncio
async def test_outbound_converter_resolves_media_and_reply() -> None:
    store = MemoryMediaStore()
    image = await store.put(b"image", "image/jpeg", "photo.jpg")
    file = await store.put(b"file", "application/octet-stream", "report.bin")
    message = IMOutboundMessage(
        segments=(
            IMSegment.text("hello"),
            IMSegment("mention", {"id": "20001"}),
            IMSegment.media("image", image),
            IMSegment.media("file", file),
        ),
        reply_to="99",
    )

    converted = await convert_outbound_message(message, store)

    assert [segment["type"] for segment in converted] == [
        "reply",
        "text",
        "at",
        "image",
        "file",
    ]
    assert converted[3]["data"]["file"].startswith("base64://")
    assert converted[4]["data"]["name"] == "report.bin"

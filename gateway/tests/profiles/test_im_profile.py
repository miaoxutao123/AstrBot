"""Standard IM profile serialization and validation tests."""

import pytest

from gateway.media import MediaMetadata
from gateway.profiles.im import (
    IM_CONVERSATION_TYPES,
    IM_MESSAGE_SCHEMA,
    IM_OUTBOUND_SCHEMA,
    IMConversation,
    IMMessage,
    IMOutboundMessage,
    IMSegment,
    IMSender,
)


def test_im_message_round_trip_supports_all_conversation_types() -> None:
    for conversation_type in IM_CONVERSATION_TYPES:
        message = IMMessage(
            message_id=f"message-{conversation_type}",
            conversation=IMConversation(conversation_type, "conversation-1"),
            sender=IMSender("user-1", "Alice"),
            segments=(IMSegment.text("hello"),),
        )

        payload = message.to_payload()

        assert payload.schema == IM_MESSAGE_SCHEMA
        assert IMMessage.from_payload(payload) == message


def test_outbound_profile_round_trip_with_media_and_reply() -> None:
    metadata = MediaMetadata(
        "media_abc",
        "image/jpeg",
        "photo.jpg",
        3,
        1.0,
        2.0,
    )
    outbound = IMOutboundMessage(
        segments=(IMSegment.text("hello"), IMSegment.media("image", metadata)),
        reply_to="message-1",
    )

    payload = outbound.to_payload()

    assert payload.schema == IM_OUTBOUND_SCHEMA
    assert IMOutboundMessage.from_payload(payload) == outbound


def test_unknown_standard_segment_is_rejected_but_raw_is_lossless() -> None:
    with pytest.raises(ValueError, match="unknown IM segment"):
        IMSegment("onebot-face", {"id": "1"})

    raw = IMSegment.raw("onebot", "face", {"id": "1", "large": True})

    assert raw.to_dict()["data"]["data"] == {"id": "1", "large": True}

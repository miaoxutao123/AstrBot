"""Telegram standard IM capability declarations."""

from gateway.core import Capability
from gateway.profiles.im import (
    IM_DELETE_SCHEMA,
    IM_EDIT_SCHEMA,
    IM_MESSAGE_DELETE,
    IM_MESSAGE_EDIT,
    IM_MESSAGE_REPLY,
    IM_MESSAGE_SEND,
    IM_REACTION_ADD,
    IM_REACTION_REMOVE,
    IM_REACTION_SCHEMA,
    IM_TYPING_SCHEMA,
    IM_TYPING_SET,
    im_capability,
)

TELEGRAM_SEGMENTS = {
    "text",
    "image",
    "audio",
    "video",
    "file",
    "mention",
    "reply",
    "location",
}

TELEGRAM_CAPABILITIES: tuple[Capability, ...] = (
    im_capability(
        IM_MESSAGE_SEND,
        supported_segments=TELEGRAM_SEGMENTS,
        max_text_length=4096,
        supports_reply=True,
        supports_thread=True,
        supports_edit=True,
    ),
    im_capability(
        IM_MESSAGE_REPLY,
        supported_segments=TELEGRAM_SEGMENTS,
        max_text_length=4096,
        supports_reply=True,
        supports_thread=True,
    ),
    Capability(IM_MESSAGE_EDIT, schema={"payload_schema": IM_EDIT_SCHEMA}),
    Capability(IM_MESSAGE_DELETE, schema={"payload_schema": IM_DELETE_SCHEMA}),
    Capability(IM_REACTION_ADD, schema={"payload_schema": IM_REACTION_SCHEMA}),
    Capability(IM_REACTION_REMOVE, schema={"payload_schema": IM_REACTION_SCHEMA}),
    Capability(IM_TYPING_SET, schema={"payload_schema": IM_TYPING_SCHEMA}),
)

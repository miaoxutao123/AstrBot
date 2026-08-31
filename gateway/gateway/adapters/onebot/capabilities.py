"""Conservative OneBot v11 capability declaration."""

from gateway.core import Capability
from gateway.profiles.im import (
    IM_MESSAGE_DELETE,
    IM_MESSAGE_REPLY,
    IM_MESSAGE_SEND,
    im_capability,
)

ONEBOT_SEGMENTS = {
    "text",
    "image",
    "audio",
    "video",
    "file",
    "mention",
    "mention_all",
    "reply",
    "json",
    "raw",
}

ONEBOT_CAPABILITIES: tuple[Capability, ...] = (
    im_capability(
        IM_MESSAGE_SEND,
        supported_segments=ONEBOT_SEGMENTS,
        supports_reply=True,
        supports_thread=False,
        supports_edit=False,
    ),
    im_capability(
        IM_MESSAGE_REPLY,
        supported_segments=ONEBOT_SEGMENTS,
        supports_reply=True,
    ),
    Capability(
        IM_MESSAGE_DELETE,
        schema={"payload_schema": "im.message.delete.v1"},
    ),
)

"""Capabilities implemented by the Satori transport."""

from gateway.core import Capability
from gateway.profiles.im import (
    IM_MESSAGE_RECEIVE,
    IM_MESSAGE_REPLY,
    IM_MESSAGE_SEND,
    im_capability,
)

SATORI_CAPABILITIES = (
    Capability(IM_MESSAGE_RECEIVE),
    im_capability(
        IM_MESSAGE_SEND,
        supported_segments=(
            "text",
            "mention",
            "image",
            "audio",
            "video",
            "file",
            "reply",
        ),
    ),
    im_capability(
        IM_MESSAGE_REPLY,
        supported_segments=(
            "text",
            "mention",
            "image",
            "audio",
            "video",
            "file",
            "reply",
        ),
    ),
)

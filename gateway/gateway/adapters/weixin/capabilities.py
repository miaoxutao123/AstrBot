"""Weixin OC standard IM capabilities."""

from gateway.core import Capability
from gateway.profiles.im import (
    IM_MESSAGE_RECEIVE,
    IM_MESSAGE_SEND,
    IM_TYPING_SCHEMA,
    IM_TYPING_SET,
    im_capability,
)

WEIXIN_SEGMENTS = {"text", "image", "video", "file"}
WEIXIN_CAPABILITIES: tuple[Capability, ...] = (
    Capability(IM_MESSAGE_RECEIVE),
    im_capability(IM_MESSAGE_SEND, supported_segments=WEIXIN_SEGMENTS),
    Capability(IM_TYPING_SET, schema={"payload_schema": IM_TYPING_SCHEMA}),
)

"""Implemented QQ Official message capabilities."""

from gateway.core import Capability
from gateway.profiles.im import IM_MESSAGE_REPLY, IM_MESSAGE_SEND, im_capability

QQ_OFFICIAL_CAPABILITIES = (
    im_capability(IM_MESSAGE_SEND, supported_segments=("text", "image", "reply")),
    im_capability(IM_MESSAGE_REPLY, supported_segments=("text", "image", "reply")),
)


def endpoint_capabilities(scene: str) -> list[Capability]:
    segments = (
        ("text", "image", "reply") if scene in {"c2c", "group"} else ("text", "reply")
    )
    return [
        im_capability(IM_MESSAGE_SEND, supported_segments=segments),
        im_capability(IM_MESSAGE_REPLY, supported_segments=segments),
    ]

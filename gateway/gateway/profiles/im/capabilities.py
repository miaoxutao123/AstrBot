"""Standard operation-level IM capability vocabulary."""

from collections.abc import Iterable
from typing import Any

from gateway.core import Capability

from .segments import IM_SEGMENT_TYPES

IM_MESSAGE_SEND = "im.message.send"
IM_MESSAGE_REPLY = "im.message.reply"
IM_MESSAGE_RECEIVE = "im.message.receive"
IM_MESSAGE_EDIT = "im.message.edit"
IM_MESSAGE_DELETE = "im.message.delete"
IM_REACTION_ADD = "im.reaction.add"
IM_REACTION_REMOVE = "im.reaction.remove"
IM_TYPING_SET = "im.typing.set"


def im_capability(
    name: str,
    *,
    supported_segments: Iterable[str] = IM_SEGMENT_TYPES,
    **metadata: Any,
) -> Capability:
    """Create a discoverable standard IM capability.

    Args:
        name: Standard operation name.
        supported_segments: Segment types supported by this operation.
        **metadata: Additional transport constraints.

    Returns:
        Core capability with IM metadata in its schema field.
    """
    return Capability(
        name,
        schema={
            "payload_schema": "im.message.outbound.v1",
            "supported_segments": sorted(set(supported_segments)),
            **metadata,
        },
    )

"""Standard inbound and outbound IM profile models."""

from collections.abc import Sequence
from dataclasses import dataclass

from gateway.core import Payload

from .segments import IMSegment
from .validation import optional_string, require_mapping, require_string

IM_MESSAGE_SCHEMA = "im.message.v1"
IM_OUTBOUND_SCHEMA = "im.message.outbound.v1"
IM_CONVERSATION_TYPES = frozenset(
    {"private", "group", "channel", "thread", "room", "unknown"}
)


@dataclass(frozen=True, slots=True)
class IMConversation:
    """Identify an IM conversation without assuming QQ semantics.

    Args:
        type: Private, group, channel, thread, room, unknown, or future type.
        id: Platform conversation identifier.
    """

    type: str
    id: str

    def __post_init__(self) -> None:
        """Validate identifiers.

        Raises:
            ValueError: If either identifier is empty.
        """
        require_string(self.type, "conversation type")
        require_string(self.id, "conversation id")

    def to_dict(self) -> dict[str, str]:
        """Serialize the conversation.

        Returns:
            JSON-compatible conversation mapping.
        """
        return {"type": self.type, "id": self.id}


@dataclass(frozen=True, slots=True)
class IMSender:
    """Describe the sender of an inbound IM event.

    Args:
        id: Platform sender identifier.
        display_name: Human-readable display name.
    """

    id: str
    display_name: str

    def __post_init__(self) -> None:
        """Validate sender fields.

        Raises:
            ValueError: If either field is empty.
        """
        require_string(self.id, "sender id")
        require_string(self.display_name, "sender display_name")

    def to_dict(self) -> dict[str, str]:
        """Serialize the sender.

        Returns:
            JSON-compatible sender mapping.
        """
        return {"id": self.id, "display_name": self.display_name}


@dataclass(frozen=True, slots=True)
class IMMessage:
    """Represent one inbound `im.message.v1` payload.

    Args:
        message_id: Stable platform message identifier.
        conversation: Source conversation.
        sender: Message sender.
        segments: Ordered standard IM segments.
        reply_to: Replied-to platform message ID.

    Raises:
        ValueError: If the message or segment collection is invalid.
    """

    message_id: str
    conversation: IMConversation
    sender: IMSender
    segments: tuple[IMSegment, ...]
    reply_to: str | None = None

    def __post_init__(self) -> None:
        """Validate message fields.

        Raises:
            ValueError: If the message ID is empty or no segments are present.
        """
        require_string(self.message_id, "message_id")
        if not self.segments:
            raise ValueError("IM message must contain at least one segment")
        optional_string(self.reply_to, "reply_to")

    def to_payload(self) -> Payload:
        """Serialize to the open Core payload envelope.

        Returns:
            `im.message.v1` payload.
        """
        return Payload(
            IM_MESSAGE_SCHEMA,
            {
                "message_id": self.message_id,
                "conversation": self.conversation.to_dict(),
                "sender": self.sender.to_dict(),
                "segments": [segment.to_dict() for segment in self.segments],
                "reply_to": self.reply_to,
            },
        )

    @classmethod
    def from_payload(cls, payload: Payload) -> "IMMessage":
        """Parse an inbound Core payload.

        Args:
            payload: Core payload with `im.message.v1` schema.

        Returns:
            Validated IM message.

        Raises:
            ValueError: If the schema or fields are invalid.
        """
        if payload.schema != IM_MESSAGE_SCHEMA:
            raise ValueError("payload is not im.message.v1")
        data = payload.data
        conversation = require_mapping(data.get("conversation"), "conversation")
        sender = require_mapping(data.get("sender"), "sender")
        raw_segments = data.get("segments")
        if not isinstance(raw_segments, Sequence) or isinstance(raw_segments, str):
            raise ValueError("segments must be an array")
        return cls(
            message_id=require_string(data.get("message_id"), "message_id"),
            conversation=IMConversation(
                require_string(conversation.get("type"), "conversation type"),
                require_string(conversation.get("id"), "conversation id"),
            ),
            sender=IMSender(
                require_string(sender.get("id"), "sender id"),
                require_string(sender.get("display_name"), "sender display_name"),
            ),
            segments=tuple(
                IMSegment.from_dict(require_mapping(segment, "segment"))
                for segment in raw_segments
            ),
            reply_to=optional_string(data.get("reply_to"), "reply_to"),
        )


@dataclass(frozen=True, slots=True)
class IMOutboundMessage:
    """Represent one `im.message.outbound.v1` command payload.

    Args:
        segments: Ordered standard IM segments.
        reply_to: Optional platform message ID to quote.
    """

    segments: tuple[IMSegment, ...]
    reply_to: str | None = None

    def __post_init__(self) -> None:
        """Validate outbound message fields.

        Raises:
            ValueError: If no segments are present or reply ID is invalid.
        """
        if not self.segments:
            raise ValueError("outbound IM message must contain at least one segment")
        optional_string(self.reply_to, "reply_to")

    def to_payload(self) -> Payload:
        """Serialize to the open Core payload envelope.

        Returns:
            `im.message.outbound.v1` payload.
        """
        return Payload(
            IM_OUTBOUND_SCHEMA,
            {
                "segments": [segment.to_dict() for segment in self.segments],
                "reply_to": self.reply_to,
            },
        )

    @classmethod
    def from_payload(cls, payload: Payload) -> "IMOutboundMessage":
        """Parse an outbound Core payload.

        Args:
            payload: Core payload with `im.message.outbound.v1` schema.

        Returns:
            Validated outbound message.

        Raises:
            ValueError: If the schema or fields are invalid.
        """
        if payload.schema != IM_OUTBOUND_SCHEMA:
            raise ValueError("payload is not im.message.outbound.v1")
        raw_segments = payload.data.get("segments")
        if not isinstance(raw_segments, Sequence) or isinstance(raw_segments, str):
            raise ValueError("segments must be an array")
        return cls(
            segments=tuple(
                IMSegment.from_dict(require_mapping(segment, "segment"))
                for segment in raw_segments
            ),
            reply_to=optional_string(payload.data.get("reply_to"), "reply_to"),
        )

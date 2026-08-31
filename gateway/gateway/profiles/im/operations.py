"""Standard IM operation payloads beyond basic send and reply."""

from collections.abc import Sequence
from dataclasses import dataclass

from gateway.core import Payload

from .segments import IMSegment
from .validation import optional_string, require_mapping, require_string

IM_EDIT_SCHEMA = "im.message.edit.v1"
IM_DELETE_SCHEMA = "im.message.delete.v1"
IM_REACTION_SCHEMA = "im.reaction.v1"
IM_TYPING_SCHEMA = "im.typing.v1"


def _segments(value: object) -> tuple[IMSegment, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise ValueError("segments must be an array")
    segments = tuple(
        IMSegment.from_dict(require_mapping(segment, "segment")) for segment in value
    )
    if not segments:
        raise ValueError("segments must not be empty")
    return segments


@dataclass(frozen=True, slots=True)
class IMMessageEdit:
    """Represent an `im.message.edit.v1` payload.

    Args:
        message_id: Platform message identifier to edit.
        segments: Replacement standard IM content.
    """

    message_id: str
    segments: tuple[IMSegment, ...]

    def __post_init__(self) -> None:
        require_string(self.message_id, "message_id")
        if not self.segments:
            raise ValueError("segments must not be empty")

    def to_payload(self) -> Payload:
        """Serialize the edit operation.

        Returns:
            Versioned Core payload.
        """
        return Payload(
            IM_EDIT_SCHEMA,
            {
                "message_id": self.message_id,
                "segments": [segment.to_dict() for segment in self.segments],
            },
        )

    @classmethod
    def from_payload(cls, payload: Payload) -> "IMMessageEdit":
        """Parse and validate an edit payload.

        Args:
            payload: Core payload envelope.

        Returns:
            Validated edit operation.
        """
        if payload.schema != IM_EDIT_SCHEMA:
            raise ValueError("payload is not im.message.edit.v1")
        return cls(
            require_string(payload.data.get("message_id"), "message_id"),
            _segments(payload.data.get("segments")),
        )


@dataclass(frozen=True, slots=True)
class IMMessageDelete:
    """Represent an `im.message.delete.v1` payload.

    Args:
        message_id: Platform message identifier to delete.
    """

    message_id: str

    def __post_init__(self) -> None:
        require_string(self.message_id, "message_id")

    def to_payload(self) -> Payload:
        """Serialize the delete operation.

        Returns:
            Versioned Core payload.
        """
        return Payload(IM_DELETE_SCHEMA, {"message_id": self.message_id})

    @classmethod
    def from_payload(cls, payload: Payload) -> "IMMessageDelete":
        """Parse and validate a delete payload.

        Args:
            payload: Core payload envelope.

        Returns:
            Validated delete operation.
        """
        if payload.schema != IM_DELETE_SCHEMA:
            raise ValueError("payload is not im.message.delete.v1")
        return cls(require_string(payload.data.get("message_id"), "message_id"))


@dataclass(frozen=True, slots=True)
class IMReaction:
    """Represent an `im.reaction.v1` payload.

    Args:
        message_id: Platform message identifier.
        emoji: Unicode emoji or platform custom-emoji identifier.
        big: Whether a platform should use its larger reaction animation.
    """

    message_id: str
    emoji: str | None
    big: bool = False

    def __post_init__(self) -> None:
        require_string(self.message_id, "message_id")
        optional_string(self.emoji, "emoji")
        if not isinstance(self.big, bool):
            raise ValueError("reaction big must be a boolean")

    def to_payload(self) -> Payload:
        """Serialize the reaction operation.

        Returns:
            Versioned Core payload.
        """
        return Payload(
            IM_REACTION_SCHEMA,
            {"message_id": self.message_id, "emoji": self.emoji, "big": self.big},
        )

    @classmethod
    def from_payload(cls, payload: Payload) -> "IMReaction":
        """Parse and validate a reaction payload.

        Args:
            payload: Core payload envelope.

        Returns:
            Validated reaction operation.
        """
        if payload.schema != IM_REACTION_SCHEMA:
            raise ValueError("payload is not im.reaction.v1")
        big = payload.data.get("big", False)
        if not isinstance(big, bool):
            raise ValueError("reaction big must be a boolean")
        return cls(
            require_string(payload.data.get("message_id"), "message_id"),
            optional_string(payload.data.get("emoji"), "emoji"),
            big,
        )


@dataclass(frozen=True, slots=True)
class IMTyping:
    """Represent an `im.typing.v1` payload.

    Args:
        action: Transport-neutral typing/upload activity name.
    """

    action: str = "typing"

    def __post_init__(self) -> None:
        require_string(self.action, "action")

    def to_payload(self) -> Payload:
        """Serialize the typing operation.

        Returns:
            Versioned Core payload.
        """
        return Payload(IM_TYPING_SCHEMA, {"action": self.action})

    @classmethod
    def from_payload(cls, payload: Payload) -> "IMTyping":
        """Parse and validate a typing payload.

        Args:
            payload: Core payload envelope.

        Returns:
            Validated typing operation.
        """
        if payload.schema != IM_TYPING_SCHEMA:
            raise ValueError("payload is not im.typing.v1")
        return cls(require_string(payload.data.get("action", "typing"), "action"))

"""Extensible IM segment v1 model."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from gateway.media import MediaMetadata

from .validation import require_mapping, require_string

IM_SEGMENT_TYPES = frozenset(
    {
        "text",
        "image",
        "audio",
        "video",
        "file",
        "mention",
        "mention_all",
        "reply",
        "location",
        "forward",
        "card",
        "json",
        "raw",
    }
)
_MEDIA_SEGMENT_TYPES = frozenset({"image", "audio", "video", "file"})


@dataclass(frozen=True, slots=True)
class IMSegment:
    """Represent one standard IM segment.

    Args:
        type: Standard IM segment type.
        data: Segment-owned JSON-compatible fields.

    Raises:
        ValueError: If the segment type or required data is invalid.
    """

    type: str
    data: dict[str, Any]

    def __post_init__(self) -> None:
        """Validate segment invariants.

        Raises:
            ValueError: If the segment is invalid.
        """
        if self.type not in IM_SEGMENT_TYPES:
            raise ValueError(f"unknown IM segment type: {self.type}")
        if self.type == "text":
            require_string(self.data.get("text"), "text segment text")
        elif self.type in _MEDIA_SEGMENT_TYPES:
            media = require_mapping(self.data.get("media"), "media segment media")
            require_string(media.get("media_id"), "media_id")
            require_string(media.get("mime_type"), "mime_type")
            require_string(media.get("filename"), "filename")
            size = media.get("size")
            if not isinstance(size, int) or size < 0:
                raise ValueError("media size must be a non-negative integer")
        elif self.type == "mention":
            require_string(self.data.get("id"), "mention id")
        elif self.type == "reply":
            require_string(self.data.get("message_id"), "reply message_id")
        elif self.type == "location":
            latitude = self.data.get("latitude")
            longitude = self.data.get("longitude")
            if not isinstance(latitude, int | float) or not isinstance(
                longitude, int | float
            ):
                raise ValueError("location coordinates must be numeric")
        elif self.type == "raw":
            require_string(self.data.get("platform"), "raw platform")
            require_mapping(self.data.get("data"), "raw data")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IMSegment":
        """Parse a segment mapping.

        Args:
            value: Segment mapping.

        Returns:
            Validated IM segment.
        """
        segment_type = require_string(value.get("type"), "segment type")
        return cls(segment_type, dict(require_mapping(value.get("data", {}), "data")))

    @classmethod
    def text(cls, text: str) -> "IMSegment":
        """Create a text segment.

        Args:
            text: Non-empty text.

        Returns:
            Text segment.
        """
        return cls("text", {"text": text})

    @classmethod
    def media(cls, segment_type: str, metadata: MediaMetadata) -> "IMSegment":
        """Create an opaque media segment.

        Args:
            segment_type: Image, audio, video, or file.
            metadata: Stored Gateway media metadata.

        Returns:
            Media segment.

        Raises:
            ValueError: If the segment type is not media.
        """
        if segment_type not in _MEDIA_SEGMENT_TYPES:
            raise ValueError("segment type is not media")
        return cls(segment_type, {"media": metadata.to_dict()})

    @classmethod
    def raw(
        cls,
        platform: str,
        segment_type: str,
        data: Mapping[str, Any],
    ) -> "IMSegment":
        """Preserve an unsupported platform segment.

        Args:
            platform: Source platform name.
            segment_type: Original segment type.
            data: Original segment data.

        Returns:
            Standard raw segment.
        """
        return cls(
            "raw",
            {
                "platform": platform,
                "segment_type": segment_type,
                "data": dict(data),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize this segment.

        Returns:
            JSON-compatible segment mapping.
        """
        return {"type": self.type, "data": dict(self.data)}

"""Media metadata and safe storage errors."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    """Describe one opaque Gateway media object.

    Args:
        media_id: Random opaque media identifier.
        mime_type: Validated MIME type.
        filename: Safe display filename.
        size: Content length in bytes.
        created_at: Unix creation timestamp.
        expires_at: Unix expiry timestamp.
    """

    media_id: str
    mime_type: str
    filename: str
    size: int
    created_at: float
    expires_at: float

    def to_dict(self) -> dict[str, str | int | float]:
        """Return the public media reference.

        Returns:
            JSON-compatible media metadata.
        """
        return {
            "media_id": self.media_id,
            "mime_type": self.mime_type,
            "filename": self.filename,
            "size": self.size,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class MediaContent:
    """Return media bytes together with metadata.

    Args:
        metadata: Public media metadata.
        data: Stored media bytes.
    """

    metadata: MediaMetadata
    data: bytes


class MediaStoreError(Exception):
    """Represent a safe media validation or lookup failure.

    Args:
        message: Public error message.
        not_found: Whether the object does not exist or expired.
    """

    def __init__(self, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.not_found = not_found

"""Bounded-size in-memory media store."""

import asyncio
import re
import secrets
import time
from pathlib import PurePath

from .interface import MediaStore
from .models import MediaContent, MediaMetadata, MediaStoreError

_MIME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")


def validate_media_input(
    data: bytes,
    mime_type: str,
    filename: str,
    max_upload_size: int,
) -> str:
    """Validate media input and return a safe filename.

    Args:
        data: Media bytes.
        mime_type: Declared MIME type.
        filename: Untrusted display filename.
        max_upload_size: Maximum accepted byte length.

    Returns:
        Safe filename without path components.

    Raises:
        MediaStoreError: If size, MIME type, or filename is invalid.
    """
    if not data:
        raise MediaStoreError("media content must not be empty")
    if len(data) > max_upload_size:
        raise MediaStoreError("media upload exceeds the configured size limit")
    normalized_mime = mime_type.strip().lower()
    if not _MIME_PATTERN.fullmatch(normalized_mime):
        raise MediaStoreError("media MIME type is invalid")
    if not filename or filename != PurePath(filename).name:
        raise MediaStoreError("media filename is invalid")
    if any(character in filename for character in {"/", "\\", "\x00", "\r", "\n", '"'}):
        raise MediaStoreError("media filename is invalid")
    return filename


class MemoryMediaStore(MediaStore):
    """Keep short-lived media objects in process memory.

    Args:
        max_upload_size: Maximum object size in bytes.
        default_ttl: Default object lifetime in seconds.
    """

    def __init__(
        self,
        max_upload_size: int = 20 * 1024 * 1024,
        default_ttl: float = 3600.0,
    ) -> None:
        if max_upload_size <= 0 or default_ttl <= 0:
            raise ValueError("media limits must be positive")
        self._max_upload_size = max_upload_size
        self._default_ttl = default_ttl
        self._objects: dict[str, MediaContent] = {}
        self._lock = asyncio.Lock()

    @property
    def max_upload_size(self) -> int:
        """Return the maximum accepted object size.

        Returns:
            Maximum size in bytes.
        """
        return self._max_upload_size

    async def put(
        self,
        data: bytes,
        mime_type: str,
        filename: str,
        ttl_seconds: float | None = None,
    ) -> MediaMetadata:
        """Store one in-memory media object.

        Args:
            data: Media bytes.
            mime_type: Declared MIME type.
            filename: Untrusted display filename.
            ttl_seconds: Optional object TTL override.

        Returns:
            Stored object metadata.

        Raises:
            MediaStoreError: If metadata or size is invalid.
        """
        safe_filename = validate_media_input(
            data,
            mime_type,
            filename,
            self._max_upload_size,
        )
        ttl = self._default_ttl if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            raise MediaStoreError("media TTL must be positive")
        now = time.time()
        metadata = MediaMetadata(
            media_id=f"media_{secrets.token_urlsafe(24)}",
            mime_type=mime_type.strip().lower(),
            filename=safe_filename,
            size=len(data),
            created_at=now,
            expires_at=now + ttl,
        )
        async with self._lock:
            self._objects[metadata.media_id] = MediaContent(metadata, bytes(data))
        return metadata

    async def get(self, media_id: str) -> MediaContent:
        """Read one non-expired object.

        Args:
            media_id: Opaque media identifier.

        Returns:
            Metadata and content bytes.

        Raises:
            MediaStoreError: If the object is absent or expired.
        """
        async with self._lock:
            content = self._objects.get(media_id)
            if content is None:
                raise MediaStoreError("media was not found", not_found=True)
            if content.metadata.expires_at <= time.time():
                self._objects.pop(media_id, None)
                raise MediaStoreError("media was not found", not_found=True)
            return content

    async def delete(self, media_id: str) -> bool:
        """Delete an object if present.

        Args:
            media_id: Opaque media identifier.

        Returns:
            Whether an object was deleted.
        """
        async with self._lock:
            return self._objects.pop(media_id, None) is not None

    async def cleanup(self) -> int:
        """Delete expired objects.

        Returns:
            Number of deleted objects.
        """
        now = time.time()
        async with self._lock:
            expired = [
                media_id
                for media_id, content in self._objects.items()
                if content.metadata.expires_at <= now
            ]
            for media_id in expired:
                self._objects.pop(media_id, None)
            return len(expired)

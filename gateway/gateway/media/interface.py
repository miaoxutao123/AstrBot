"""Abstract media store contract."""

from abc import ABC, abstractmethod

from .models import MediaContent, MediaMetadata


class MediaStore(ABC):
    """Store opaque media without exposing host filesystem paths."""

    @property
    @abstractmethod
    def max_upload_size(self) -> int:
        """Return the maximum accepted object size.

        Returns:
            Maximum size in bytes.
        """
        raise NotImplementedError

    @abstractmethod
    async def put(
        self,
        data: bytes,
        mime_type: str,
        filename: str,
        ttl_seconds: float | None = None,
    ) -> MediaMetadata:
        """Store bytes and return an opaque reference.

        Args:
            data: Media bytes.
            mime_type: Declared MIME type.
            filename: Untrusted display filename.
            ttl_seconds: Optional object TTL override.

        Returns:
            Stored object metadata.
        """
        raise NotImplementedError

    @abstractmethod
    async def get(self, media_id: str) -> MediaContent:
        """Read one non-expired media object.

        Args:
            media_id: Opaque media identifier.

        Returns:
            Metadata and content bytes.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete(self, media_id: str) -> bool:
        """Delete an object if present.

        Args:
            media_id: Opaque media identifier.

        Returns:
            Whether an object was deleted.
        """
        raise NotImplementedError

    @abstractmethod
    async def cleanup(self) -> int:
        """Delete expired objects.

        Returns:
            Number of deleted objects.
        """
        raise NotImplementedError

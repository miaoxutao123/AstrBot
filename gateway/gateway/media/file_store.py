"""Temporary file-backed media store with a persistent metadata index."""

import asyncio
import json
import secrets
import time
from pathlib import Path

from .interface import MediaStore
from .memory import validate_media_input
from .models import MediaContent, MediaMetadata, MediaStoreError


class FileMediaStore(MediaStore):
    """Store media under a host-controlled directory.

    Args:
        directory: Dedicated media data directory.
        max_upload_size: Maximum object size in bytes.
        default_ttl: Default object lifetime in seconds.
    """

    def __init__(
        self,
        directory: Path,
        max_upload_size: int = 20 * 1024 * 1024,
        default_ttl: float = 3600.0,
    ) -> None:
        if max_upload_size <= 0 or default_ttl <= 0:
            raise ValueError("media limits must be positive")
        self._directory = directory.resolve()
        self._directory.mkdir(parents=True, exist_ok=True)
        self._index_path = self._directory / "index.json"
        self._max_upload_size = max_upload_size
        self._default_ttl = default_ttl
        self._metadata = self._load_index()
        self._lock = asyncio.Lock()

    def _load_index(self) -> dict[str, MediaMetadata]:
        if not self._index_path.exists():
            return {}
        try:
            values = json.loads(self._index_path.read_text(encoding="utf-8"))
            if not isinstance(values, list):
                raise ValueError("media index must be an array")
            metadata = {
                str(value["media_id"]): MediaMetadata(
                    media_id=str(value["media_id"]),
                    mime_type=str(value["mime_type"]),
                    filename=str(value["filename"]),
                    size=int(value["size"]),
                    created_at=float(value["created_at"]),
                    expires_at=float(value["expires_at"]),
                )
                for value in values
                if isinstance(value, dict)
            }
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("media metadata index is invalid") from exc
        for media_id in metadata:
            self._path(media_id)
        return metadata

    def _persist_index(self) -> None:
        temporary = self._directory / f"index.{secrets.token_hex(8)}.tmp"
        serialized = json.dumps(
            [metadata.to_dict() for metadata in self._metadata.values()],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(self._index_path)

    @property
    def max_upload_size(self) -> int:
        """Return the maximum accepted object size.

        Returns:
            Maximum size in bytes.
        """
        return self._max_upload_size

    def _path(self, media_id: str) -> Path:
        if (
            not media_id.startswith("media_")
            or not media_id[6:].replace("-", "").replace("_", "").isalnum()
        ):
            raise MediaStoreError("media was not found", not_found=True)
        path = (self._directory / f"{media_id}.bin").resolve()
        if path.parent != self._directory:
            raise MediaStoreError("media was not found", not_found=True)
        return path

    async def put(
        self,
        data: bytes,
        mime_type: str,
        filename: str,
        ttl_seconds: float | None = None,
    ) -> MediaMetadata:
        """Store bytes in the dedicated media directory.

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
        path = self._path(metadata.media_id)
        async with self._lock:
            await asyncio.to_thread(path.write_bytes, data)
            self._metadata[metadata.media_id] = metadata
            await asyncio.to_thread(self._persist_index)
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
        path = self._path(media_id)
        async with self._lock:
            metadata = self._metadata.get(media_id)
            if metadata is None or metadata.expires_at <= time.time():
                self._metadata.pop(media_id, None)
                if path.exists():
                    await asyncio.to_thread(path.unlink)
                await asyncio.to_thread(self._persist_index)
                raise MediaStoreError("media was not found", not_found=True)
            try:
                data = await asyncio.to_thread(path.read_bytes)
            except FileNotFoundError as exc:
                self._metadata.pop(media_id, None)
                await asyncio.to_thread(self._persist_index)
                raise MediaStoreError("media was not found", not_found=True) from exc
            return MediaContent(metadata, data)

    async def delete(self, media_id: str) -> bool:
        """Delete an object if present.

        Args:
            media_id: Opaque media identifier.

        Returns:
            Whether an object was deleted.
        """
        path = self._path(media_id)
        async with self._lock:
            metadata = self._metadata.pop(media_id, None)
            existed = path.exists()
            if existed:
                await asyncio.to_thread(path.unlink)
            if metadata is not None:
                await asyncio.to_thread(self._persist_index)
            return metadata is not None or existed

    async def cleanup(self) -> int:
        """Delete expired objects.

        Returns:
            Number of deleted objects.
        """
        now = time.time()
        async with self._lock:
            expired = [
                media_id
                for media_id, metadata in self._metadata.items()
                if metadata.expires_at <= now
            ]
            for media_id in expired:
                self._metadata.pop(media_id, None)
                path = self._path(media_id)
                if path.exists():
                    await asyncio.to_thread(path.unlink)
            if expired:
                await asyncio.to_thread(self._persist_index)
            return len(expired)

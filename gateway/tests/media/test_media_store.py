"""Media store security, expiry, and persistence tests."""

import asyncio
from pathlib import Path

import pytest

from gateway.media import FileMediaStore, MediaStoreError, MemoryMediaStore


@pytest.mark.asyncio
@pytest.mark.parametrize("store_type", ["memory", "file"])
async def test_media_store_round_trip_and_delete(
    store_type: str,
    tmp_path: Path,
) -> None:
    store = (
        MemoryMediaStore(max_upload_size=10)
        if store_type == "memory"
        else FileMediaStore(tmp_path / "media", max_upload_size=10)
    )

    metadata = await store.put(b"abc", "image/png", "photo.png")
    content = await store.get(metadata.media_id)

    assert metadata.media_id.startswith("media_")
    assert content.data == b"abc"
    assert content.metadata.filename == "photo.png"
    assert await store.delete(metadata.media_id)
    with pytest.raises(MediaStoreError, match="not found"):
        await store.get(metadata.media_id)


@pytest.mark.asyncio
async def test_media_store_rejects_size_mime_and_path_traversal() -> None:
    store = MemoryMediaStore(max_upload_size=3)

    with pytest.raises(MediaStoreError, match="size limit"):
        await store.put(b"abcd", "image/png", "photo.png")
    with pytest.raises(MediaStoreError, match="MIME"):
        await store.put(b"a", "bad\r\ntype", "photo.png")
    with pytest.raises(MediaStoreError, match="filename"):
        await store.put(b"a", "image/png", "../photo.png")


@pytest.mark.asyncio
async def test_media_store_expiry_cleanup() -> None:
    store = MemoryMediaStore(default_ttl=0.001)
    metadata = await store.put(b"abc", "text/plain", "note.txt")
    await asyncio.sleep(0.01)

    assert await store.cleanup() == 1
    with pytest.raises(MediaStoreError, match="not found"):
        await store.get(metadata.media_id)


@pytest.mark.asyncio
async def test_file_media_metadata_survives_store_recreation(tmp_path: Path) -> None:
    directory = tmp_path / "media"
    first = FileMediaStore(directory)
    metadata = await first.put(b"abc", "text/plain", "note.txt")

    second = FileMediaStore(directory)

    assert (await second.get(metadata.media_id)).data == b"abc"

"""Media API authorization and object lifecycle tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.api import ApiKey, create_app
from gateway.core import AdapterRegistry, AdapterRuntime, MemoryEventBus
from gateway.media import MemoryMediaStore


def build_media_app() -> FastAPI:
    """Build an API with a small media size limit.

    Returns:
        FastAPI application.
    """
    event_bus = MemoryEventBus()
    runtime = AdapterRuntime(
        AdapterRegistry(),
        event_bus,
        media_store=MemoryMediaStore(max_upload_size=4),
    )
    return create_app(
        runtime,
        event_bus,
        [
            ApiKey(
                "media",
                "media-secret",
                frozenset({"media:read", "media:write"}),
            )
        ],
    )


def test_media_api_upload_download_delete_and_size_limit() -> None:
    app = build_media_app()
    headers = {"Authorization": "Bearer media-secret"}

    with TestClient(app) as client:
        unauthorized = client.post(
            "/v1/media",
            files={"upload": ("a.txt", b"abc", "text/plain")},
        )
        uploaded = client.post(
            "/v1/media",
            headers=headers,
            files={"upload": ("报告.txt", b"abc", "text/plain")},
        )
        media_id = uploaded.json()["media"]["media_id"]
        downloaded = client.get(f"/v1/media/{media_id}", headers=headers)
        oversized = client.post(
            "/v1/media",
            headers=headers,
            files={"upload": ("large.txt", b"abcde", "text/plain")},
        )
        deleted = client.delete(f"/v1/media/{media_id}", headers=headers)
        missing = client.get(f"/v1/media/{media_id}", headers=headers)

    assert unauthorized.status_code == 401
    assert uploaded.status_code == 200
    assert downloaded.content == b"abc"
    assert downloaded.headers["content-type"] == "text/plain; charset=utf-8"
    assert "%E6%8A%A5%E5%91%8A.txt" in downloaded.headers["content-disposition"]
    assert oversized.status_code == 400
    assert oversized.json()["error"]["code"] == "MEDIA_INVALID"
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "MEDIA_NOT_FOUND"

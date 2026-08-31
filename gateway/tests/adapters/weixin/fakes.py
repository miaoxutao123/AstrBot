"""Deterministic Weixin OC client."""

import asyncio
from collections.abc import Mapping
from typing import Any


class FakeWeixinClient:
    def __init__(self) -> None:
        self.auth_results: asyncio.Queue[Mapping[str, Any]] = asyncio.Queue()
        self.updates: asyncio.Queue[Mapping[str, Any]] = asyncio.Queue()
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.uploads: list[tuple[bytes, bytes]] = []
        self.downloads: dict[str, bytes] = {"image-query": b"image-bytes"}
        self.closed = False

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        token: str | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append((method, endpoint, dict(payload or params or {})))
        if endpoint.endswith("get_bot_qrcode"):
            return {"qrcode": "qr-secret", "qrcode_img_content": "weixin://login/qr"}
        if endpoint.endswith("get_qrcode_status"):
            return await self.auth_results.get()
        if endpoint.endswith("getupdates"):
            return await self.updates.get()
        if endpoint.endswith("getuploadurl"):
            return {"upload_param": "upload-param"}
        if endpoint.endswith("getconfig"):
            return {"typing_ticket": "ticket"}
        return {"ret": 0, "errcode": 0}

    async def upload(
        self,
        upload_url: str,
        upload_param: str,
        file_key: str,
        key: bytes,
        data: bytes,
    ) -> str:
        self.uploads.append((key, data))
        return "download-param"

    async def download(
        self,
        encrypted_query_param: str,
        key_value: str | None,
        max_size: int,
    ) -> bytes:
        value = self.downloads[encrypted_query_param]
        if len(value) > max_size:
            raise ValueError("media too large")
        return value

    async def close(self) -> None:
        self.closed = True

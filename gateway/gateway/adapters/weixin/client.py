"""Narrow Weixin OC HTTP and encrypted-CDN client."""

import base64
import json
import random
from collections.abc import Mapping
from typing import Any, Protocol, cast
from urllib.parse import quote

from .config import WeixinConfig
from .errors import WeixinAuthenticationError, WeixinNetworkError, WeixinRequestError


class WeixinClient(Protocol):
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
    ) -> Mapping[str, Any]: ...
    async def upload(
        self, upload_url: str, upload_param: str, file_key: str, key: bytes, data: bytes
    ) -> str: ...
    async def download(
        self,
        encrypted_query_param: str,
        key_value: str | None,
        max_size: int,
    ) -> bytes: ...
    async def close(self) -> None: ...


def _pad(data: bytes) -> bytes:
    size = 16 - len(data) % 16
    return data + bytes([size]) * size


def _unpad(data: bytes) -> bytes:
    if not data:
        return data
    size = data[-1]
    return (
        data[:-size]
        if 0 < size <= 16 and data[-size:] == bytes([size]) * size
        else data
    )


def parse_media_key(value: str) -> bytes:
    normalized = value.strip()
    decoded = base64.b64decode(normalized + "=" * (-len(normalized) % 4))
    if len(decoded) == 16:
        return decoded
    text = decoded.decode("ascii", errors="ignore")
    if len(decoded) == 32 and all(
        character in "0123456789abcdefABCDEF" for character in text
    ):
        return bytes.fromhex(text)
    raise WeixinRequestError("unsupported Weixin media key")


class AiohttpWeixinClient:
    def __init__(self, config: WeixinConfig) -> None:
        self.config = config
        self._session: Any = None

    async def _ensure_session(self) -> Any:
        if self._session is None or self._session.closed:
            try:
                import aiohttp
            except ImportError as exc:
                raise WeixinNetworkError("aiohttp is unavailable") from exc
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.api_timeout)
            )
        return self._session

    @staticmethod
    def _headers(token: str | None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": base64.b64encode(
                str(random.getrandbits(32)).encode()
            ).decode(),
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

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
        session = await self._ensure_session()
        merged = self._headers(token)
        merged.update(headers or {})
        try:
            async with session.request(
                method,
                f"{self.config.base_url}/{endpoint.lstrip('/')}",
                params=params,
                json=payload,
                headers=merged,
                timeout=timeout or self.config.api_timeout,
            ) as response:
                text = await response.text()
                if response.status in {401, 403} and token:
                    raise WeixinAuthenticationError("Weixin session token was rejected")
                if response.status >= 400:
                    raise WeixinRequestError(
                        f"Weixin request failed with HTTP {response.status}"
                    )
                data = json.loads(text) if text else {}
        except (WeixinAuthenticationError, WeixinRequestError):
            raise
        except Exception as exc:
            raise WeixinNetworkError("Weixin request failed") from exc
        if not isinstance(data, Mapping):
            raise WeixinRequestError("Weixin response is not an object")
        return cast(Mapping[str, Any], data)

    async def upload(
        self, upload_url: str, upload_param: str, file_key: str, key: bytes, data: bytes
    ) -> str:
        try:
            from Crypto.Cipher import AES
        except ImportError as exc:
            raise WeixinNetworkError("pycryptodome is unavailable") from exc
        url = (
            upload_url
            or f"{self.config.cdn_base_url}/upload?encrypted_query_param={quote(upload_param)}&filekey={quote(file_key)}"
        )
        session = await self._ensure_session()
        try:
            async with session.post(
                url,
                data=AES.new(key, AES.MODE_ECB).encrypt(_pad(data)),
                headers={"Content-Type": "application/octet-stream"},
            ) as response:
                if response.status != 200:
                    raise WeixinRequestError(
                        f"Weixin CDN upload failed with HTTP {response.status}"
                    )
                result = response.headers.get("x-encrypted-param", "")
        except WeixinRequestError:
            raise
        except Exception as exc:
            raise WeixinNetworkError("Weixin CDN upload failed") from exc
        if not result:
            raise WeixinRequestError(
                "Weixin CDN upload response is missing a download parameter"
            )
        return str(result)

    async def download(
        self,
        encrypted_query_param: str,
        key_value: str | None,
        max_size: int,
    ) -> bytes:
        session = await self._ensure_session()
        url = f"{self.config.cdn_base_url}/download?encrypted_query_param={quote(encrypted_query_param)}"
        wire_limit = max_size + 16 if key_value is not None else max_size
        try:
            async with session.get(url) as response:
                if response.status >= 400:
                    raise WeixinRequestError(
                        f"Weixin CDN download failed with HTTP {response.status}"
                    )
                declared_size = response.content_length
                if declared_size is not None and declared_size > wire_limit:
                    raise WeixinRequestError(
                        "Weixin CDN media exceeds the configured size limit"
                    )
                chunks: list[bytes] = []
                received = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    received += len(chunk)
                    if received > wire_limit:
                        raise WeixinRequestError(
                            "Weixin CDN media exceeds the configured size limit"
                        )
                    chunks.append(bytes(chunk))
                data = b"".join(chunks)
        except WeixinRequestError:
            raise
        except Exception as exc:
            raise WeixinNetworkError("Weixin CDN download failed") from exc
        if key_value is None:
            return data
        try:
            from Crypto.Cipher import AES
        except ImportError as exc:
            raise WeixinNetworkError("pycryptodome is unavailable") from exc
        decrypted = _unpad(
            AES.new(parse_media_key(key_value), AES.MODE_ECB).decrypt(data)
        )
        if len(decrypted) > max_size:
            raise WeixinRequestError(
                "Weixin CDN media exceeds the configured size limit"
            )
        return decrypted

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None


def create_client(config: WeixinConfig) -> WeixinClient:
    return AiohttpWeixinClient(config)

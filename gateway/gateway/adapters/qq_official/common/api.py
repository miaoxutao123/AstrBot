"""Transport-neutral QQ Official REST boundary shared by adapters."""

from collections.abc import Mapping
from typing import Any, Protocol


class QQOfficialAPI(Protocol):
    async def request(
        self, method: str, path: str, data: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]: ...

    async def download(
        self, url: str, max_size: int
    ) -> tuple[bytes, str | None, str | None]: ...

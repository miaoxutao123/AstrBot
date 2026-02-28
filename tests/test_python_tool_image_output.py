import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from astrbot.core.computer.tools.python import handle_result


class _DummyEvent:
    def __init__(self, platform: str = "qq") -> None:
        self._platform = platform
        self.sent_messages = []

    def get_platform_name(self) -> str:
        return self._platform

    async def send(self, message):
        self.sent_messages.append(message)


@pytest.mark.asyncio
async def test_handle_result_accepts_non_png_image_mime():
    event = _DummyEvent(platform="qq")
    result = {
        "data": {
            "output": {
                "text": "",
                "images": [{"image/jpeg": "aGVsbG8="}],
            },
            "error": "",
        }
    }

    resp = await handle_result(result, event)
    assert len(resp.content) == 1
    assert getattr(resp.content[0], "mimeType", "") == "image/jpeg"
    assert getattr(resp.content[0], "data", "") == "aGVsbG8="

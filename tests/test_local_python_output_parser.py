import base64
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from astrbot.core.computer.booters.local import _extract_python_outputs


def test_extract_python_outputs_parses_image_data_line():
    stdout = "\n".join(
        [
            "before",
            "IMAGE_DATA:aGVsbG8=",
            "after",
        ]
    )

    text, images = _extract_python_outputs(stdout)

    assert text == "before\nafter"
    assert len(images) == 1
    assert images[0] == {"image/png": "aGVsbG8="}


def test_extract_python_outputs_parses_data_url_mime():
    stdout = "IMAGE_DATA:data:image/jpeg;base64,aGVsbG8="

    text, images = _extract_python_outputs(stdout)

    assert text == ""
    assert images == [{"image/jpeg": "aGVsbG8="}]


def test_extract_python_outputs_parses_astrbot_image_output(tmp_path):
    image_path = tmp_path / "shot.png"
    # 1x1 transparent png
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
    )

    stdout = f"[ASTRBOT_IMAGE_OUTPUT#magic]: {image_path}\nhello"
    text, images = _extract_python_outputs(stdout)

    assert text == "hello"
    assert len(images) == 1
    assert "image/png" in images[0]
    assert images[0]["image/png"].startswith("iVBOR")

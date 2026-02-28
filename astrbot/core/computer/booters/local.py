from __future__ import annotations

import asyncio
import base64
import binascii
import mimetypes
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import (
    get_astrbot_data_path,
    get_astrbot_root,
    get_astrbot_temp_path,
)

from ..olayer import FileSystemComponent, PythonComponent, ShellComponent
from .base import ComputerBooter

_BLOCKED_COMMAND_PATTERNS = [
    " rm -rf ",
    " rm -fr ",
    " rm -r ",
    " mkfs",
    " dd if=",
    " shutdown",
    " reboot",
    " poweroff",
    " halt",
    " sudo ",
    ":(){:|:&};:",
    " kill -9 ",
    " killall ",
]


def _is_safe_command(command: str) -> bool:
    cmd = f" {command.strip().lower()} "
    return not any(pat in cmd for pat in _BLOCKED_COMMAND_PATTERNS)


def _ensure_safe_path(path: str) -> str:
    abs_path = os.path.abspath(path)
    allowed_roots = [
        os.path.abspath(get_astrbot_root()),
        os.path.abspath(get_astrbot_data_path()),
        os.path.abspath(get_astrbot_temp_path()),
    ]
    if not any(abs_path.startswith(root) for root in allowed_roots):
        raise PermissionError("Path is outside the allowed computer roots.")
    return abs_path


_ASTRBOT_TEXT_OUTPUT_RE = re.compile(
    r"^\[ASTRBOT_TEXT_OUTPUT#[^\]]+\]:\s?(?P<text>.*)$"
)
_ASTRBOT_IMAGE_OUTPUT_RE = re.compile(
    r"^\[ASTRBOT_IMAGE_OUTPUT#[^\]]+\]:\s?(?P<path>.*)$"
)
_ASTRBOT_FILE_OUTPUT_RE = re.compile(
    r"^\[ASTRBOT_FILE_OUTPUT#[^\]]+\]:\s?(?P<path>.*)$"
)
_DATA_URL_IMAGE_RE = re.compile(
    r"^data:(?P<mime>image/[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$",
    re.IGNORECASE,
)


def _decode_inline_image_data(payload: str) -> dict[str, str] | None:
    raw = (payload or "").strip()
    if not raw:
        return None

    mime_type = "image/png"
    b64_data = raw
    match = _DATA_URL_IMAGE_RE.match(raw)
    if match:
        mime_type = match.group("mime").lower()
        b64_data = match.group("data")

    # Compact newlines/spaces that may come from wrapped output.
    b64_data = "".join(b64_data.split())
    try:
        base64.b64decode(b64_data, validate=True)
    except (ValueError, binascii.Error):
        return None
    return {mime_type: b64_data}


def _encode_image_file(path: str) -> dict[str, str] | None:
    if not path:
        return None
    image_path = os.path.abspath(path)
    if not os.path.isfile(image_path):
        return None

    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/png"

    try:
        with open(image_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
    except OSError:
        return None
    return {mime_type: data}


def _extract_python_outputs(stdout: str) -> tuple[str, list[dict[str, str]]]:
    if not stdout:
        return "", []

    images: list[dict[str, str]] = []
    text_lines: list[str] = []

    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("IMAGE_DATA:"):
            image_payload = _decode_inline_image_data(stripped.split(":", 1)[1])
            if image_payload is not None:
                images.append(image_payload)
                continue

        image_match = _ASTRBOT_IMAGE_OUTPUT_RE.match(stripped)
        if image_match:
            image_payload = _encode_image_file(image_match.group("path").strip())
            if image_payload is not None:
                images.append(image_payload)
                continue

        text_match = _ASTRBOT_TEXT_OUTPUT_RE.match(line)
        if text_match:
            text_lines.append(text_match.group("text"))
            continue

        file_match = _ASTRBOT_FILE_OUTPUT_RE.match(stripped)
        if file_match:
            text_lines.append(f"[file] {file_match.group('path').strip()}")
            continue

        text_lines.append(line)

    return "\n".join(text_lines), images


@dataclass
class LocalShellComponent(ShellComponent):
    async def exec(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = 30,
        shell: bool = True,
        background: bool = False,
    ) -> dict[str, Any]:
        if not _is_safe_command(command):
            raise PermissionError("Blocked unsafe shell command.")

        def _run() -> dict[str, Any]:
            run_env = os.environ.copy()
            if env:
                run_env.update({str(k): str(v) for k, v in env.items()})
            working_dir = _ensure_safe_path(cwd) if cwd else get_astrbot_root()
            if background:
                proc = subprocess.Popen(
                    command,
                    shell=shell,
                    cwd=working_dir,
                    env=run_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                return {"pid": proc.pid, "stdout": "", "stderr": "", "exit_code": None}
            result = subprocess.run(
                command,
                shell=shell,
                cwd=working_dir,
                env=run_env,
                timeout=timeout,
                capture_output=True,
                text=True,
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
            }

        return await asyncio.to_thread(_run)


@dataclass
class LocalPythonComponent(PythonComponent):
    async def exec(
        self,
        code: str,
        kernel_id: str | None = None,
        timeout: int = 30,
        silent: bool = False,
    ) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            try:
                result = subprocess.run(
                    [os.environ.get("PYTHON", sys.executable), "-c", code],
                    timeout=timeout,
                    capture_output=True,
                    text=True,
                )
                stdout = "" if silent else result.stdout
                stderr = result.stderr if result.returncode != 0 else ""
                parsed_text, parsed_images = _extract_python_outputs(stdout)
                return {
                    "data": {
                        "output": {"text": parsed_text, "images": parsed_images},
                        "error": stderr,
                    }
                }
            except subprocess.TimeoutExpired:
                return {
                    "data": {
                        "output": {"text": "", "images": []},
                        "error": "Execution timed out.",
                    }
                }

        return await asyncio.to_thread(_run)


@dataclass
class LocalFileSystemComponent(FileSystemComponent):
    async def create_file(
        self, path: str, content: str = "", mode: int = 0o644
    ) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            abs_path = _ensure_safe_path(path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(abs_path, mode)
            return {"success": True, "path": abs_path}

        return await asyncio.to_thread(_run)

    async def read_file(self, path: str, encoding: str = "utf-8") -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            abs_path = _ensure_safe_path(path)
            with open(abs_path, encoding=encoding) as f:
                content = f.read()
            return {"success": True, "content": content}

        return await asyncio.to_thread(_run)

    async def write_file(
        self, path: str, content: str, mode: str = "w", encoding: str = "utf-8"
    ) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            abs_path = _ensure_safe_path(path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, mode, encoding=encoding) as f:
                f.write(content)
            return {"success": True, "path": abs_path}

        return await asyncio.to_thread(_run)

    async def delete_file(self, path: str) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            abs_path = _ensure_safe_path(path)
            if os.path.isdir(abs_path):
                shutil.rmtree(abs_path)
            else:
                os.remove(abs_path)
            return {"success": True, "path": abs_path}

        return await asyncio.to_thread(_run)

    async def list_dir(
        self, path: str = ".", show_hidden: bool = False
    ) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            abs_path = _ensure_safe_path(path)
            entries = os.listdir(abs_path)
            if not show_hidden:
                entries = [e for e in entries if not e.startswith(".")]
            return {"success": True, "entries": entries}

        return await asyncio.to_thread(_run)


class LocalBooter(ComputerBooter):
    def __init__(self) -> None:
        self._fs = LocalFileSystemComponent()
        self._python = LocalPythonComponent()
        self._shell = LocalShellComponent()

    async def boot(self, session_id: str) -> None:
        logger.info(f"Local computer booter initialized for session: {session_id}")

    async def shutdown(self) -> None:
        logger.info("Local computer booter shutdown complete.")

    @property
    def fs(self) -> FileSystemComponent:
        return self._fs

    @property
    def python(self) -> PythonComponent:
        return self._python

    @property
    def shell(self) -> ShellComponent:
        return self._shell

    async def upload_file(self, path: str, file_name: str) -> dict:
        raise NotImplementedError(
            "LocalBooter does not support upload_file operation. Use shell instead."
        )

    async def download_file(self, remote_path: str, local_path: str) -> None:
        raise NotImplementedError(
            "LocalBooter does not support download_file operation. Use shell instead."
        )

    async def available(self) -> bool:
        return True

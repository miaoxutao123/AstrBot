"""Safe generic command and HTTP AgentResult invokers."""

import asyncio
import json
import os
from collections.abc import Mapping
from typing import Any

import httpx


class CommandInvoker:
    def __init__(self, command: tuple[str, ...], timeout: float, max_stdout: int, allowlist: tuple[str, ...]) -> None:
        self.command, self.timeout, self.max_stdout, self.allowlist = command, timeout, max_stdout, allowlist

    async def invoke(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        env = {key: os.environ[key] for key in self.allowlist if key in os.environ}
        process = await asyncio.create_subprocess_exec(*self.command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        raw = json.dumps(value).encode()
        try:
            stdout, _stderr = await asyncio.wait_for(process.communicate(raw), self.timeout)
        except asyncio.TimeoutError:
            process.kill(); await process.wait(); raise
        if process.returncode != 0 or len(stdout) > self.max_stdout:
            raise RuntimeError("agent command failed or exceeded stdout limit")
        result = json.loads(stdout)
        if not isinstance(result, Mapping): raise ValueError("agent command returned non-object JSON")
        return result


class HttpInvoker:
    def __init__(self, url: str, timeout: float) -> None:
        self.url, self.timeout = url, timeout

    async def invoke(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.url, json=value)
            response.raise_for_status(); result = response.json()
        if not isinstance(result, Mapping): raise ValueError("agent HTTP endpoint returned non-object JSON")
        return result

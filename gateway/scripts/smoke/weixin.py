"""Protected interactive Phase 5 real-environment Weixin smoke test."""

import argparse
import asyncio
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import aiohttp


def _ws_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    return urlunparse(
        (
            "wss" if parsed.scheme == "https" else "ws",
            parsed.netloc,
            "/v1/events/ws",
            "",
            "",
            "",
        )
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:6186")
    parser.add_argument("--api-key-env", default="GATEWAY_API_KEY")
    parser.add_argument("--adapter-id", default="weixin-main")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise RuntimeError(
            f"API key environment variable is missing: {args.api_key_env}"
        )
    if not args.image.is_file():
        raise RuntimeError("smoke image does not exist")
    base = args.gateway.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}

    async with aiohttp.ClientSession(headers=headers) as session:

        async def auth(method: str = "GET", suffix: str = "") -> dict[str, Any]:
            async with session.request(
                method, f"{base}/v1/adapters/{args.adapter_id}/auth{suffix}"
            ) as response:
                result = await response.json()
                if response.status != 200:
                    raise RuntimeError(f"Weixin auth API failed: {result}")
                return dict(result)

        async def wait_auth(expected: str) -> dict[str, Any]:
            deadline = asyncio.get_running_loop().time() + args.timeout
            while asyncio.get_running_loop().time() < deadline:
                result = await auth()
                if result.get("status") == expected:
                    return result
                await asyncio.sleep(1)
            raise RuntimeError(f"Weixin auth did not reach {expected}")

        async def command(
            operation: str, endpoint: str, data: dict[str, Any], command_id: str
        ) -> dict[str, Any]:
            async with session.post(
                f"{base}/v1/commands",
                json={
                    "id": command_id,
                    "target": {
                        "transport": "im",
                        "adapter_id": args.adapter_id,
                        "endpoint_id": endpoint,
                    },
                    "type": operation,
                    "payload": {
                        "schema": "im.typing.v1"
                        if operation == "im.typing.set"
                        else "im.message.outbound.v1",
                        "data": data,
                    },
                },
            ) as response:
                result = await response.json()
                if response.status != 200 or result.get("status") != "success":
                    raise RuntimeError(f"Weixin command failed: {result}")
                return dict(result)

        async def upload(path: Path) -> dict[str, Any]:
            form = aiohttp.FormData()
            form.add_field(
                "upload",
                await asyncio.to_thread(path.read_bytes),
                filename=path.name,
                content_type=mimetypes.guess_type(path.name)[0]
                or "application/octet-stream",
            )
            async with session.post(f"{base}/v1/media", data=form) as response:
                result = await response.json()
                if response.status != 200:
                    raise RuntimeError(f"Gateway media upload failed: {result}")
                return dict(result["media"])

        current = await auth()
        if current.get("status") != "authenticated":
            challenge = await auth("POST", "/start")
            details = challenge.get("challenge", {})
            print(f"打开二维码 URI 并使用微信确认登录：{details.get('qr_uri')}")
            await wait_auth("authenticated")

        print("请从微信向该账号发送一条文字消息和一张图片。")
        text_event: dict[str, Any] | None = None
        media_seen = False
        async with session.ws_connect(_ws_url(base)) as websocket:
            deadline = asyncio.get_running_loop().time() + args.timeout
            while asyncio.get_running_loop().time() < deadline and (
                text_event is None or not media_seen
            ):
                envelope = await asyncio.wait_for(
                    websocket.receive_json(), timeout=args.timeout
                )
                if envelope.get("type") != "event":
                    continue
                event = envelope["data"]
                if event.get("source", {}).get("adapter_id") != args.adapter_id:
                    continue
                segments = event.get("payload", {}).get("data", {}).get("segments", [])
                if any(segment.get("type") == "text" for segment in segments):
                    text_event = event
                if any(
                    segment.get("type") in {"image", "audio", "video", "file"}
                    for segment in segments
                ):
                    media_seen = True
        if text_event is None or not media_seen:
            raise RuntimeError("Weixin inbound text/media validation timed out")
        endpoint = str(text_event["source"]["endpoint_id"])
        await command(
            "im.message.send",
            endpoint,
            {"segments": [{"type": "text", "data": {"text": "Weixin Phase 5 smoke"}}]},
            "weixin-smoke-text",
        )
        await command(
            "im.typing.set", endpoint, {"action": "typing"}, "weixin-smoke-typing"
        )
        image = await upload(args.image)
        await command(
            "im.message.send",
            endpoint,
            {"segments": [{"type": "image", "data": {"media": image}}]},
            "weixin-smoke-image",
        )

        await asyncio.to_thread(
            input, "现在重启 Gateway，启动完成后按 Enter；脚本将验证会话恢复："
        )
        await wait_auth("authenticated")
        await command(
            "im.message.send",
            endpoint,
            {"segments": [{"type": "text", "data": {"text": "Session restored"}}]},
            "weixin-smoke-restored",
        )

        await asyncio.to_thread(
            input, "现在在微信侧注销/使 token 失效，等待 Gateway 检测；操作后按 Enter："
        )
        await wait_auth("logged_out")
        challenge = await auth("POST", "/start")
        print(f"重新扫码登录：{challenge.get('challenge', {}).get('qr_uri')}")
        await wait_auth("authenticated")
    print("REAL_SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

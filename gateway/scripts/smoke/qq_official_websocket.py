"""Protected QQ Official WebSocket real-environment smoke test."""

import argparse
import asyncio
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import aiohttp


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:6186")
    parser.add_argument("--api-key-env", default="GATEWAY_API_KEY")
    parser.add_argument("--adapter-id", default="qq-official-main")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise RuntimeError(
            f"API key environment variable is missing: {args.api_key_env}"
        )
    base = args.gateway.rstrip("/")
    parsed = urlparse(base)
    ws_url = urlunparse(
        (
            "wss" if parsed.scheme == "https" else "ws",
            parsed.netloc,
            "/v1/events/ws",
            "",
            "",
            "",
        )
    )
    headers = {"Authorization": f"Bearer {api_key}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(f"{base}/v1/adapters/{args.adapter_id}") as response:
            state = await response.json()
            if response.status != 200 or state.get("state") != "running":
                raise RuntimeError(f"QQ Official adapter is not running: {state}")
        print("Send one authorized C2C, group, or guild/channel message to the QQ bot.")
        async with session.ws_connect(ws_url) as socket:
            while True:
                envelope = await asyncio.wait_for(socket.receive_json(), args.timeout)
                if (
                    envelope.get("type") == "event"
                    and envelope.get("data", {}).get("source", {}).get("adapter_id")
                    == args.adapter_id
                ):
                    event = envelope["data"]
                    break

        async def command(command_id: str, segments: list[dict[str, object]]) -> None:
            async with session.post(
                f"{base}/v1/commands",
                json={
                    "id": command_id,
                    "target": event["source"],
                    "type": "im.message.reply",
                    "payload": {
                        "schema": "im.message.outbound.v1",
                        "data": {
                            "reply_to": event["payload"]["data"]["message_id"],
                            "segments": segments,
                        },
                    },
                },
            ) as response:
                result = await response.json()
                if response.status != 200 or result.get("status") != "success":
                    raise RuntimeError(f"QQ Official command failed: {result}")

        await command(
            "qq-official-real-smoke-text",
            [{"type": "text", "data": {"text": "QQ Official real smoke reply"}}],
        )
        if args.image is not None:
            if not args.image.is_file():
                raise RuntimeError("smoke image does not exist")
            form = aiohttp.FormData()
            form.add_field(
                "upload",
                await asyncio.to_thread(args.image.read_bytes),
                filename=args.image.name,
                content_type=mimetypes.guess_type(args.image.name)[0] or "image/png",
            )
            async with session.post(f"{base}/v1/media", data=form) as response:
                uploaded = await response.json()
                if response.status != 200:
                    raise RuntimeError(f"Gateway media upload failed: {uploaded}")
            await command(
                "qq-official-real-smoke-image",
                [{"type": "image", "data": {"media": uploaded["media"]}}],
            )
        print(
            "Interrupt Gateway connectivity, restore it, and verify resume/reconnect."
        )
        await asyncio.to_thread(
            input, "Press Enter after DEGRADED then RUNNING was observed: "
        )
        async with session.get(f"{base}/v1/adapters/{args.adapter_id}") as response:
            state = await response.json()
            if state.get("state") != "running":
                raise RuntimeError(f"QQ Official did not recover: {state}")
    print("REAL_SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""Manual real-environment Telegram Phase 4 smoke test.

The script prints REAL_SMOKE_PASS only after real private/group receive, text,
image, file, reply, reaction, edit, typing, and polling reconnect checks succeed.
"""

import argparse
import asyncio
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import aiohttp


def websocket_url(base_url: str, query: dict[str, str] | None = None) -> str:
    """Build the authenticated Gateway event WebSocket URL.

    Args:
        base_url: Gateway HTTP base URL.
        query: Optional event-stream query parameters.

    Returns:
        Gateway event WebSocket URL.
    """
    parsed = urlparse(base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse(
        (scheme, parsed.netloc, "/v1/events/ws", "", urlencode(query or {}), "")
    )


async def main() -> int:
    """Run the interactive real Telegram validation sequence.

    Returns:
        Process exit code after every real-platform check succeeds.

    Raises:
        RuntimeError: If credentials, transport state, events, or commands fail.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:6186")
    parser.add_argument("--api-key-env", default="GATEWAY_API_KEY")
    parser.add_argument("--adapter-id", default="telegram-main")
    parser.add_argument("--private-chat-id", required=True)
    parser.add_argument("--group-chat-id", required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise RuntimeError(
            f"API key environment variable is missing: {args.api_key_env}"
        )
    if not args.image.is_file() or not args.file.is_file():
        raise RuntimeError("smoke image or file does not exist")
    headers = {"Authorization": f"Bearer {api_key}"}
    base_url = args.gateway.rstrip("/")

    async with aiohttp.ClientSession(headers=headers) as session:

        async def adapter_state() -> str:
            async with session.get(
                f"{base_url}/v1/adapters/{args.adapter_id}"
            ) as response:
                value = await response.json()
                if response.status != 200:
                    raise RuntimeError("Telegram adapter is unavailable")
                return str(value.get("state", "unknown"))

        async def wait_for_state(expected: str) -> None:
            deadline = asyncio.get_running_loop().time() + args.timeout
            while asyncio.get_running_loop().time() < deadline:
                state = await adapter_state()
                if state == expected:
                    return
                if state == "failed":
                    raise RuntimeError("Telegram adapter entered FAILED state")
                await asyncio.sleep(1)
            raise RuntimeError(f"Telegram adapter did not reach {expected}")

        async def command(
            command_id: str,
            endpoint_id: str,
            operation: str,
            schema: str,
            data: dict[str, Any],
        ) -> dict[str, Any]:
            async with session.post(
                f"{base_url}/v1/commands",
                json={
                    "id": command_id,
                    "target": {
                        "transport": "im",
                        "adapter_id": args.adapter_id,
                        "endpoint_id": endpoint_id,
                    },
                    "type": operation,
                    "payload": {"schema": schema, "data": data},
                },
            ) as response:
                result = await response.json()
                if response.status != 200 or result.get("status") != "success":
                    raise RuntimeError(f"Telegram command failed: {result}")
                return result

        async def upload(path: Path) -> dict[str, Any]:
            form = aiohttp.FormData()
            content = await asyncio.to_thread(path.read_bytes)
            form.add_field(
                "upload",
                content,
                filename=path.name,
                content_type=(
                    mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                ),
            )
            async with session.post(f"{base_url}/v1/media", data=form) as response:
                result = await response.json()
                if response.status != 200:
                    raise RuntimeError(f"Telegram media upload failed: {result}")
                return dict(result["media"])

        if await adapter_state() != "running":
            raise RuntimeError("Telegram adapter is not connected")
        print("Send one private message and one group message to the Telegram bot.")
        observed: dict[str, dict[str, Any]] = {}
        async with session.ws_connect(websocket_url(base_url)) as websocket:
            while set(observed) != {"private", "group"}:
                message = await asyncio.wait_for(
                    websocket.receive_json(), timeout=args.timeout
                )
                if message.get("type") != "event":
                    continue
                event = message["data"]
                endpoint = str(event.get("source", {}).get("endpoint_id", ""))
                if endpoint == f"private:{args.private_chat_id}":
                    observed["private"] = event
                elif endpoint == f"group:{args.group_chat_id}" or endpoint.startswith(
                    f"thread:{args.group_chat_id}:"
                ):
                    observed["group"] = event

        private_endpoint = f"private:{args.private_chat_id}"
        group_endpoint = str(observed["group"]["source"]["endpoint_id"])
        await command(
            "telegram-smoke-private-text",
            private_endpoint,
            "im.message.send",
            "im.message.outbound.v1",
            {"segments": [{"type": "text", "data": {"text": "Private smoke"}}]},
        )
        group_sent = await command(
            "telegram-smoke-group-text",
            group_endpoint,
            "im.message.send",
            "im.message.outbound.v1",
            {"segments": [{"type": "text", "data": {"text": "Group smoke"}}]},
        )
        sent_id = str(group_sent.get("external_id"))
        if not sent_id or sent_id == "None":
            raise RuntimeError("Telegram send did not return a message ID")
        reply_to = str(observed["group"]["payload"]["data"]["message_id"])
        await command(
            "telegram-smoke-reply",
            group_endpoint,
            "im.message.reply",
            "im.message.outbound.v1",
            {
                "reply_to": reply_to,
                "segments": [{"type": "text", "data": {"text": "Reply smoke"}}],
            },
        )
        image = await upload(args.image)
        file = await upload(args.file)
        for label, segment_type, media in (
            ("image", "image", image),
            ("file", "file", file),
        ):
            await command(
                f"telegram-smoke-{label}",
                group_endpoint,
                "im.message.send",
                "im.message.outbound.v1",
                {"segments": [{"type": segment_type, "data": {"media": media}}]},
            )
        await command(
            "telegram-smoke-reaction",
            group_endpoint,
            "im.reaction.add",
            "im.reaction.v1",
            {"message_id": sent_id, "emoji": "👍"},
        )
        await command(
            "telegram-smoke-edit",
            group_endpoint,
            "im.message.edit",
            "im.message.edit.v1",
            {
                "message_id": sent_id,
                "segments": [{"type": "text", "data": {"text": "Edited group smoke"}}],
            },
        )
        await command(
            "telegram-smoke-typing",
            group_endpoint,
            "im.typing.set",
            "im.typing.v1",
            {"action": "typing"},
        )
        print("Block Telegram API connectivity now; waiting for DEGRADED state.")
        await wait_for_state("degraded")
        print("Restore Telegram API connectivity; waiting for RUNNING state.")
        await wait_for_state("running")
    print("REAL_SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

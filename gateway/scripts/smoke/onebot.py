"""Manual real-environment OneBot v11 smoke test.

Run only against a configured Gateway and real OneBot implementation. The script
prints REAL_SMOKE_PASS only after observing real private and group events and
successfully sending text, image, and quoted-reply commands.
"""

import argparse
import asyncio
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import aiohttp


def websocket_url(base_url: str, query: dict[str, str] | None = None) -> str:
    """Build the Gateway WebSocket URL.

    Args:
        base_url: Gateway HTTP base URL.
        query: Optional query parameters.

    Returns:
        WebSocket event endpoint URL.
    """
    parsed = urlparse(base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse(
        (scheme, parsed.netloc, "/v1/events/ws", "", urlencode(query or {}), "")
    )


async def main() -> int:
    """Run the interactive real-platform smoke sequence.

    Returns:
        Process exit code.

    Raises:
        RuntimeError: If credentials, events, media, or commands fail.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:6186")
    parser.add_argument("--api-key-env", default="GATEWAY_API_KEY")
    parser.add_argument("--adapter-id", default="qq-main")
    parser.add_argument("--private-id", required=True)
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise RuntimeError(
            f"API key environment variable is missing: {args.api_key_env}"
        )
    if not args.image.is_file():
        raise RuntimeError("smoke image file does not exist")
    headers = {"Authorization": f"Bearer {api_key}"}
    base_url = args.gateway.rstrip("/")
    async with aiohttp.ClientSession(headers=headers) as session:

        async def adapter_state() -> str:
            async with session.get(
                f"{base_url}/v1/adapters/{args.adapter_id}"
            ) as response:
                adapter = await response.json()
                if response.status != 200:
                    raise RuntimeError("OneBot adapter is not available")
                return str(adapter.get("state", "unknown"))

        async def wait_for_state(expected: str) -> None:
            deadline = asyncio.get_running_loop().time() + args.timeout
            while asyncio.get_running_loop().time() < deadline:
                state = await adapter_state()
                if state == expected:
                    return
                if state == "failed":
                    raise RuntimeError("OneBot adapter entered FAILED state")
                await asyncio.sleep(1)
            raise RuntimeError(f"OneBot adapter did not reach {expected}")

        if await adapter_state() != "running":
            raise RuntimeError("OneBot adapter is not connected")
        print("Send one private QQ message and one group QQ message now.")
        observed: dict[str, dict[str, Any]] = {}
        last_event_id = ""
        async with session.ws_connect(websocket_url(base_url)) as websocket:
            while set(observed) != {"private", "group"}:
                message = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=args.timeout,
                )
                if message.get("type") != "event":
                    continue
                event = message["data"]
                endpoint = event.get("source", {}).get("endpoint_id", "")
                if endpoint == f"private:{args.private_id}":
                    observed["private"] = event
                elif endpoint == f"group:{args.group_id}":
                    observed["group"] = event
                last_event_id = str(event["id"])

        async with session.ws_connect(
            websocket_url(base_url, {"last_event_id": last_event_id})
        ):
            pass

        async def send(
            command_id: str,
            endpoint_id: str,
            segments: list[dict[str, Any]],
            reply_to: str | None = None,
        ) -> None:
            payload: dict[str, Any] = {"segments": segments}
            if reply_to is not None:
                payload["reply_to"] = reply_to
            async with session.post(
                f"{base_url}/v1/commands",
                json={
                    "id": command_id,
                    "target": {
                        "family": "im",
                        "adapter_type": "onebot",
                        "adapter_id": args.adapter_id,
                        "endpoint_id": endpoint_id,
                    },
                    "type": "im.message.reply" if reply_to else "im.message.send",
                    "payload": {
                        "schema": "im.message.outbound.v1",
                        "data": payload,
                    },
                },
            ) as response:
                result = await response.json()
                if response.status != 200 or result.get("status") != "success":
                    raise RuntimeError(f"OneBot command failed: {result}")

        await send(
            "smoke-private-text",
            f"private:{args.private_id}",
            [{"type": "text", "data": {"text": "Gateway private smoke"}}],
        )
        group_message_id = observed["group"]["payload"]["data"]["message_id"]
        await send(
            "smoke-group-reply",
            f"group:{args.group_id}",
            [{"type": "text", "data": {"text": "Gateway reply smoke"}}],
            str(group_message_id),
        )
        form = aiohttp.FormData()
        form.add_field(
            "upload",
            args.image.read_bytes(),
            filename=args.image.name,
            content_type="image/jpeg",
        )
        async with session.post(f"{base_url}/v1/media", data=form) as response:
            media_result = await response.json()
            if response.status != 200:
                raise RuntimeError(f"media upload failed: {media_result}")
        await send(
            "smoke-group-image",
            f"group:{args.group_id}",
            [
                {
                    "type": "image",
                    "data": {"media": media_result["media"]},
                }
            ],
        )
        print("Stop the real OneBot WebSocket peer now; waiting for DEGRADED state.")
        await wait_for_state("degraded")
        print("Start the real OneBot WebSocket peer again; waiting for RUNNING state.")
        await wait_for_state("running")
    print("REAL_SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

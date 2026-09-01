"""Protected real-environment Satori smoke test."""

import argparse
import asyncio
import os
from urllib.parse import urlparse, urlunparse

import aiohttp


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:6186")
    parser.add_argument("--api-key-env", default="GATEWAY_API_KEY")
    parser.add_argument("--adapter-id", default="satori-main")
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
                raise RuntimeError(f"Satori adapter is not running: {state}")
        print("Send a direct or channel message through any Satori downstream login.")
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
        async with session.post(
            f"{base}/v1/commands",
            json={
                "id": "satori-real-smoke-reply",
                "target": event["source"],
                "type": "im.message.reply",
                "payload": {
                    "schema": "im.message.outbound.v1",
                    "data": {
                        "reply_to": event["payload"]["data"]["message_id"],
                        "segments": [
                            {
                                "type": "text",
                                "data": {"text": "Satori real smoke reply"},
                            }
                        ],
                    },
                },
            },
        ) as response:
            result = await response.json()
            if response.status != 200 or result.get("status") != "success":
                raise RuntimeError(f"Satori reply failed: {result}")
        print(
            "Interrupt the Satori server, restore it, and verify DEGRADED then RUNNING in the adapter API."
        )
        await asyncio.to_thread(
            input, "Press Enter only after reconnect has been observed: "
        )
        async with session.get(f"{base}/v1/adapters/{args.adapter_id}") as response:
            state = await response.json()
            if state.get("state") != "running":
                raise RuntimeError(f"Satori did not recover: {state}")
    print("REAL_SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

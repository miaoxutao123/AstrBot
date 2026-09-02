"""Smallest useful AstrBot-Gateway Python agent."""

import asyncio
import os

from astrbot_gateway_sdk import AsyncGatewayClient


async def main() -> None:
    base_url = os.environ.get("GATEWAY_URL", "http://127.0.0.1:6186")
    api_key = os.environ["GATEWAY_API_KEY"]
    async with AsyncGatewayClient(base_url, api_key=api_key) as gateway:
        health = await gateway.health()
        if health["status"] != "ok":
            print(f"Gateway is {health['status']}; waiting for events anyway")
        async for event in gateway.events(event_type="im.message"):
            if event.message is None:
                continue
            await gateway.reply(event, f"echo: {event.message.text}")


if __name__ == "__main__":
    asyncio.run(main())

"""MCP tool surface implemented exclusively through the public SDK."""

import asyncio
import os
from typing import Any

from astrbot_gateway_sdk import AsyncGatewayClient, GatewayEvent
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("AstrBot-Gateway")


def _client() -> AsyncGatewayClient:
    url = os.environ.get("GATEWAY_URL", "http://127.0.0.1:6186")
    return AsyncGatewayClient(url, api_key=os.environ.get("GATEWAY_API_KEY"))


@mcp.tool()
async def gateway_discover() -> dict[str, Any]:
    """Discover online Gateway adapters, endpoints, directions and permissions."""
    async with _client() as client: return dict((await client.discover()).raw)


@mcp.tool()
async def gateway_list_adapters() -> list[dict[str, Any]]:
    """List configured Gateway adapters."""
    async with _client() as client: return [dict(item) for item in await client.list_adapters()]


@mcp.tool()
async def gateway_find_endpoints(**filters: str) -> list[dict[str, Any]]:
    """Find endpoints by public identity, capability or direction."""
    async with _client() as client: return [dict(item) for item in await client.find_endpoints(**filters)]


@mcp.tool()
async def gateway_get_capabilities(endpoint: dict[str, Any]) -> list[dict[str, Any]]:
    """Get endpoint capabilities."""
    async with _client() as client: return [dict(item) for item in await client.get_capabilities(endpoint)]


@mcp.tool()
async def im_send_message(endpoint: dict[str, Any], text: str) -> dict[str, Any]:
    """Send canonical text through an IM endpoint."""
    async with _client() as client: return dict(await client.send_text(endpoint, text))


@mcp.tool()
async def im_reply_to(event: dict[str, Any], text: str) -> dict[str, Any]:
    """Reply to a previously received canonical Gateway event."""
    async with _client() as client: return dict(await client.reply(GatewayEvent.from_wire(event), text))


@mcp.tool()
async def gateway_execute(endpoint: dict[str, Any], command_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Generic future-capability escape hatch subject to Gateway authorization."""
    async with _client() as client:
        return dict(await client._command(client._endpoint_wire(endpoint), command_type, payload))


def main() -> None:
    """Run the stdio MCP server."""
    asyncio.run(mcp.run_stdio_async())

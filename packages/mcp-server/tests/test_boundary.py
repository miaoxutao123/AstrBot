"""MCP remains a public-SDK client, never a Gateway implementation client."""

from pathlib import Path


def test_mcp_uses_public_sdk_execute_surface() -> None:
    source = (Path(__file__).parents[1] / "src" / "astrbot_gateway_mcp" / "server.py").read_text(encoding="utf-8")
    assert "client.execute(" in source
    assert "client._command(" not in source
    assert "gateway.core" not in source


def test_mcp_server_imports() -> None:
    from astrbot_gateway_mcp import server

    assert server.mcp is not None

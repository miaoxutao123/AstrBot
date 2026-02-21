from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

MCP_PRESETS: dict[str, dict[str, Any]] = {
    "wolframalpha": {
        "description": (
            "Symbolic math and science computing preset. "
            "Set endpoint/access_token according to your deployed MCP gateway."
        ),
        "default_config": {
            "transport": "streamable_http",
            "url": "https://your-wolframalpha-mcp-gateway.example.com/mcp",
            "headers": {
                "Authorization": "Bearer ${WOLFRAMALPHA_APP_ID}",
            },
            "timeout": 30,
            "active": True,
            "provider": "preset",
        },
    },
    "figma": {
        "description": (
            "Figma design/prototyping preset. "
            "Set endpoint/access_token to your Figma MCP bridge."
        ),
        "default_config": {
            "transport": "streamable_http",
            "url": "https://your-figma-mcp-bridge.example.com/mcp",
            "headers": {
                "Authorization": "Bearer ${FIGMA_ACCESS_TOKEN}",
            },
            "timeout": 30,
            "active": True,
            "provider": "preset",
        },
    },
}


@dataclass
class MCPPresetListTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_mcp_preset_list"
    description: str = "List built-in MCP server presets for professional toolchains (e.g. wolframalpha, figma)."
    parameters: dict = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    async def call(self, context: ContextWrapper[AstrAgentContext]) -> ToolExecResult:
        return json.dumps(
            [
                {
                    "preset": name,
                    "description": payload.get("description", ""),
                    "default_config": payload.get("default_config", {}),
                }
                for name, payload in MCP_PRESETS.items()
            ],
            ensure_ascii=False,
        )


@dataclass
class MCPPresetInstallTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_mcp_preset_install"
    description: str = "Install an MCP server preset into mcp_server.json with optional endpoint/token override, then optionally enable it."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "preset_name": {
                    "type": "string",
                    "description": "Preset name. One of: wolframalpha, figma.",
                },
                "server_name": {
                    "type": "string",
                    "description": "Custom server key in mcp_server.json. Defaults to preset_name.",
                    "default": "",
                },
                "endpoint": {
                    "type": "string",
                    "description": "Optional endpoint override.",
                    "default": "",
                },
                "access_token": {
                    "type": "string",
                    "description": "Optional bearer token. If provided, writes Authorization header.",
                    "default": "",
                },
                "auto_enable": {
                    "type": "boolean",
                    "description": "Whether to call enable_mcp_server immediately.",
                    "default": False,
                },
            },
            "required": ["preset_name"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        preset_name: str,
        server_name: str = "",
        endpoint: str = "",
        access_token: str = "",
        auto_enable: bool = False,
    ) -> ToolExecResult:
        if context.context.event.role != "admin":
            return "error: Permission denied. Installing MCP presets is only allowed for admin users."

        preset_key = preset_name.strip().lower()
        if preset_key not in MCP_PRESETS:
            return f"error: unknown preset: {preset_name}"

        final_name = (server_name or preset_key).strip()
        if not final_name:
            return "error: invalid server_name"

        tool_mgr = context.context.context.get_llm_tool_manager()
        cfg = tool_mgr.load_mcp_config()
        servers = cfg.setdefault("mcpServers", {})

        server_cfg = copy.deepcopy(MCP_PRESETS[preset_key]["default_config"])
        if endpoint:
            server_cfg["url"] = endpoint
        if access_token:
            headers = server_cfg.setdefault("headers", {})
            headers["Authorization"] = f"Bearer {access_token}"

        servers[final_name] = server_cfg
        ok = tool_mgr.save_mcp_config(cfg)
        if not ok:
            return "error: failed to save mcp_server.json"

        enabled = False
        enable_error = ""
        if auto_enable:
            try:
                await tool_mgr.enable_mcp_server(
                    name=final_name,
                    config=server_cfg,
                    timeout=30,
                )
                enabled = True
            except Exception as exc:  # noqa: BLE001
                enable_error = str(exc)

        return json.dumps(
            {
                "preset": preset_key,
                "server_name": final_name,
                "saved": True,
                "auto_enable": auto_enable,
                "enabled": enabled,
                "enable_error": enable_error,
                "server_config": server_cfg,
            },
            ensure_ascii=False,
        )


MCP_PRESET_LIST_TOOL = MCPPresetListTool()
MCP_PRESET_INSTALL_TOOL = MCPPresetInstallTool()

__all__ = [
    "MCP_PRESETS",
    "MCP_PRESET_LIST_TOOL",
    "MCP_PRESET_INSTALL_TOOL",
    "MCPPresetListTool",
    "MCPPresetInstallTool",
]

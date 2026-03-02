import platform
from dataclasses import dataclass, field

import mcp

from astrbot.api import FunctionTool
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext, AstrMessageEvent
from astrbot.core.computer.computer_client import get_booter, get_local_booter
from astrbot.core.computer.tools.permissions import check_admin_permission
from astrbot.core.message.message_event_result import MessageChain

_OS_NAME = platform.system()

param_schema = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": "The Python code to execute.",
        },
        "silent": {
            "type": "boolean",
            "description": "Whether to suppress the output of the code execution.",
        },
    },
    "required": ["code"],
}


@dataclass
class PythonTool(FunctionTool):
    name: str = "astrbot_execute_ipython"
    description: str = f"Run codes in an IPython shell. Current OS: {_OS_NAME}."
    parameters: dict = field(default_factory=lambda: param_schema)

    async def execute(self, event: AstrMessageEvent, ctx: ContextWrapper, **kwargs) -> ToolExecResult:
        code = kwargs.get("code")
        silent = kwargs.get("silent", False)
        if not code:
            return ToolExecResult(error="No code provided.")

        booter = await get_booter(ctx.get_agent_context(AstrAgentContext))
        if not booter:
            return ToolExecResult(error="No IPython environment available.")

        result = await booter.execute_ipython(code, silent)
        return ToolExecResult(
            message_chain=MessageChain().text(result.strip()) if result else None
        )


@dataclass
class LocalPythonTool(FunctionTool):
    name: str = "astrbot_execute_python"
    description: str = (
        f"Execute codes in a Python environment. Current OS: {_OS_NAME}. "
        "Use system-compatible commands."
    )
    parameters: dict = field(default_factory=lambda: param_schema)

    async def execute(self, event: AstrMessageEvent, ctx: ContextWrapper, **kwargs) -> ToolExecResult:
        code = kwargs.get("code")
        silent = kwargs.get("silent", False)
        if not code:
            return ToolExecResult(error="No code provided.")

        check_result = await check_admin_permission(event, ctx.get_agent_context(AstrAgentContext))
        if check_result:
            return check_result

        booter = await get_local_booter(ctx.get_agent_context(AstrAgentContext))
        if not booter:
            return ToolExecResult(error="No Local Python environment available.")

        result = await booter.execute_python(code, silent)
        return ToolExecResult(
            message_chain=MessageChain().text(result.strip()) if result else None
        )

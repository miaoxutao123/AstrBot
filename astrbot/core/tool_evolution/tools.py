from __future__ import annotations

import json
from dataclasses import dataclass, field

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.runtime.resilience_monitor import coding_resilience_monitor
from astrbot.core.tool_evolution.manager import tool_evolution_manager


@dataclass
class ToolEvolutionOverviewTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_tool_evolution_overview"
    description: str = "Show recent tool execution health, active adaptation policies, and anti-overfit guardrails."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Optional tool name filter.",
                    "default": "",
                },
                "window": {
                    "type": "integer",
                    "description": "Recent call window size.",
                    "default": 200,
                },
            },
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        tool_name: str = "",
        window: int = 200,
    ) -> ToolExecResult:
        if context.context.event.role != "admin":
            return "error: Permission denied. Tool evolution overview is only allowed for admin users."
        data = await tool_evolution_manager.get_overview(
            tool_name=tool_name or None,
            window=window,
        )
        return json.dumps(data, ensure_ascii=False)


@dataclass
class ToolEvolutionProposeTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_tool_evolution_propose"
    description: str = "Propose guarded runtime adaptation policy for a tool based on historical failures/timeouts, with train-valid split anti-overfit checks."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Target tool name.",
                },
                "min_samples": {
                    "type": "integer",
                    "description": "Minimum sample requirement.",
                    "default": 12,
                },
            },
            "required": ["tool_name"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        tool_name: str,
        min_samples: int = 12,
    ) -> ToolExecResult:
        if context.context.event.role != "admin":
            return "error: Permission denied. Tool evolution proposal is only allowed for admin users."
        data = await tool_evolution_manager.propose_policy(
            tool_name=tool_name,
            min_samples=min_samples,
        )
        return json.dumps(data, ensure_ascii=False)


@dataclass
class ToolEvolutionApplyTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_tool_evolution_apply"
    description: str = "Apply (or dry-run) a guarded runtime adaptation policy for a tool. Includes anti-overfit checks and auto-rollback guard."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Target tool name.",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, return preview without applying policy.",
                    "default": True,
                },
                "min_samples": {
                    "type": "integer",
                    "description": "Minimum sample requirement.",
                    "default": 12,
                },
            },
            "required": ["tool_name"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        tool_name: str,
        dry_run: bool = True,
        min_samples: int = 12,
    ) -> ToolExecResult:
        if context.context.event.role != "admin":
            return "error: Permission denied. Tool evolution apply is only allowed for admin users."
        data = await tool_evolution_manager.apply_policy(
            tool_name=tool_name,
            dry_run=dry_run,
            min_samples=min_samples,
        )
        return json.dumps(data, ensure_ascii=False)


@dataclass
class ToolEvolutionGuardrailsTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_tool_evolution_guardrails"
    description: str = (
        "Show anti-overfit guardrails used by runtime tool self-iteration."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
    ) -> ToolExecResult:
        if context.context.event.role != "admin":
            return "error: Permission denied. Tool evolution guardrails are only allowed for admin users."
        data = await tool_evolution_manager.get_guardrails()
        return json.dumps(data, ensure_ascii=False)


@dataclass
class ToolEvolutionResilienceTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_tool_evolution_resilience"
    description: str = "Show coding resilience counters (LLM retries, stream fallback recoveries, step auto-continue outcomes)."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "reset": {
                    "type": "boolean",
                    "description": "If true, reset resilience counters after reading.",
                    "default": False,
                }
            },
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        reset: bool = False,
    ) -> ToolExecResult:
        if context.context.event.role != "admin":
            return "error: Permission denied. Coding resilience stats are only allowed for admin users."
        data = (
            await coding_resilience_monitor.reset()
            if reset
            else await coding_resilience_monitor.get_snapshot()
        )
        return json.dumps(data, ensure_ascii=False)


TOOL_EVOLUTION_OVERVIEW_TOOL = ToolEvolutionOverviewTool()
TOOL_EVOLUTION_PROPOSE_TOOL = ToolEvolutionProposeTool()
TOOL_EVOLUTION_APPLY_TOOL = ToolEvolutionApplyTool()
TOOL_EVOLUTION_GUARDRAILS_TOOL = ToolEvolutionGuardrailsTool()
TOOL_EVOLUTION_RESILIENCE_TOOL = ToolEvolutionResilienceTool()

__all__ = [
    "TOOL_EVOLUTION_OVERVIEW_TOOL",
    "TOOL_EVOLUTION_PROPOSE_TOOL",
    "TOOL_EVOLUTION_APPLY_TOOL",
    "TOOL_EVOLUTION_GUARDRAILS_TOOL",
    "TOOL_EVOLUTION_RESILIENCE_TOOL",
    "ToolEvolutionOverviewTool",
    "ToolEvolutionProposeTool",
    "ToolEvolutionApplyTool",
    "ToolEvolutionGuardrailsTool",
    "ToolEvolutionResilienceTool",
]

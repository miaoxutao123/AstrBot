from __future__ import annotations

import json
from dataclasses import dataclass, field

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.runtime.background_task_manager import background_task_manager


def _is_task_accessible(context: ContextWrapper[AstrAgentContext], task: dict) -> bool:
    event = context.context.event
    if event.role == "admin":
        return True
    return str(task.get("session_id") or "") == event.unified_msg_origin


@dataclass
class BackgroundTaskStatusTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_background_task_status"
    description: str = "Query background task status by task_id."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Background task id.",
                }
            },
            "required": ["task_id"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        task_id: str,
    ) -> ToolExecResult:
        task = await background_task_manager.get_task(task_id)
        if not task:
            return f"error: background task not found: {task_id}"
        if not _is_task_accessible(context, task):
            return "error: Permission denied. You can only access background tasks from your own session."
        return json.dumps(task, ensure_ascii=False)


@dataclass
class BackgroundTaskListTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_background_task_list"
    description: str = (
        "List recent background tasks for observability and closed-loop tracking."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of tasks.",
                    "default": 20,
                },
                "status": {
                    "type": "string",
                    "description": "Optional status filter: queued/running/retrying/succeeded/failed/cancelled.",
                    "default": "",
                },
                "session_id": {
                    "type": "string",
                    "description": "Optional session filter.",
                    "default": "",
                },
            },
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        limit: int = 20,
        status: str = "",
        session_id: str = "",
    ) -> ToolExecResult:
        event = context.context.event
        if event.role != "admin":
            session_id = event.unified_msg_origin

        tasks = await background_task_manager.list_tasks(
            limit=limit,
            status=status or None,
            session_id=session_id or None,
        )
        return json.dumps(tasks, ensure_ascii=False)


@dataclass
class BackgroundTaskCancelTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_background_task_cancel"
    description: str = "Cancel an in-flight background task."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Background task id.",
                }
            },
            "required": ["task_id"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        task_id: str,
    ) -> ToolExecResult:
        task = await background_task_manager.get_task(task_id)
        if not task:
            return f"error: background task not found: {task_id}"
        if not _is_task_accessible(context, task):
            return "error: Permission denied. You can only cancel background tasks from your own session."

        ok = await background_task_manager.cancel_task(task_id)
        if not ok:
            return f"error: failed to cancel task: {task_id}"
        task = await background_task_manager.get_task(task_id)
        return json.dumps(task, ensure_ascii=False) if task else "cancelled"


BACKGROUND_TASK_STATUS_TOOL = BackgroundTaskStatusTool()
BACKGROUND_TASK_LIST_TOOL = BackgroundTaskListTool()
BACKGROUND_TASK_CANCEL_TOOL = BackgroundTaskCancelTool()

__all__ = [
    "BACKGROUND_TASK_STATUS_TOOL",
    "BACKGROUND_TASK_LIST_TOOL",
    "BACKGROUND_TASK_CANCEL_TOOL",
    "BackgroundTaskStatusTool",
    "BackgroundTaskListTool",
    "BackgroundTaskCancelTool",
]

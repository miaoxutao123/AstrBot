from typing import Any

from mcp.types import CallToolResult, TextContent

from astrbot import logger
from astrbot.core.agent.hooks import BaseAgentRunHooks
from astrbot.core.agent.message import Message
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.long_term_memory.scope import (
    resolve_ltm_read_targets,
    resolve_ltm_scope,
)
from astrbot.core.pipeline.context_utils import call_event_hook
from astrbot.core.star.star_handler import EventType


def _get_ltm_config(run_context) -> dict:
    """Extract LTM config from run_context, returns empty dict if unavailable."""
    try:
        plugin_context = run_context.context.context
        event = run_context.context.event
        if hasattr(plugin_context, "get_config"):
            if hasattr(event, "unified_msg_origin"):
                cfg = plugin_context.get_config(umo=event.unified_msg_origin)
            else:
                cfg = plugin_context.get_config()
            if isinstance(cfg, dict):
                ltm_settings = cfg.get("provider_ltm_settings", {})
                if isinstance(ltm_settings, dict):
                    return ltm_settings.get("long_term_memory", {})
    except Exception:
        pass
    return {}


class MainAgentHooks(BaseAgentRunHooks[AstrAgentContext]):
    async def on_agent_begin(self, run_context):
        # Inject long-term memory context into system prompt
        try:
            from astrbot.core.long_term_memory.manager import get_ltm_manager

            ltm = get_ltm_manager()
            if ltm is None:
                return

            event = run_context.context.event
            ltm_cfg = _get_ltm_config(run_context)
            if not ltm_cfg or not ltm_cfg.get("enable", False):
                return

            read_cfg = ltm_cfg.get("read_policy", {})
            if not read_cfg.get("enable", True):
                return

            scope, scope_id, additional_scopes = resolve_ltm_read_targets(
                event,
                ltm_cfg=ltm_cfg,
            )

            from astrbot.core.long_term_memory.policy import MemoryReadPolicy

            read_policy = MemoryReadPolicy.from_dict(read_cfg)
            query_text = (
                event.message_str
                if hasattr(event, "message_str") and isinstance(event.message_str, str)
                else None
            )
            memory_context = await ltm.retrieve_memory_context(
                scope=scope,
                scope_id=scope_id,
                read_policy=read_policy,
                query_text=query_text,
                additional_scopes=additional_scopes,
            )

            if memory_context and run_context.messages:
                first_msg = run_context.messages[0]
                if isinstance(first_msg, Message) and first_msg.role == "system":
                    if isinstance(first_msg.content, str):
                        first_msg.content = memory_context + "\n" + first_msg.content
        except Exception as e:
            logger.debug("LTM on_agent_begin failed: %s", e)

    async def on_agent_done(self, run_context, llm_response) -> None:
        # 执行事件钩子
        if llm_response and llm_response.reasoning_content:
            # we will use this in result_decorate stage to inject reasoning content to chain
            run_context.context.event.set_extra(
                "_llm_reasoning_content", llm_response.reasoning_content
            )

        await call_event_hook(
            run_context.context.event,
            EventType.OnLLMResponseEvent,
            llm_response,
        )

        # Record conversation turn for LTM extraction
        try:
            from astrbot.core.long_term_memory.manager import get_ltm_manager

            ltm = get_ltm_manager()
            if ltm is None:
                return

            event = run_context.context.event
            ltm_cfg = _get_ltm_config(run_context)
            if not ltm_cfg or not ltm_cfg.get("enable", False):
                return
            if ltm_cfg.get("emergency_read_only", False):
                return

            scope, scope_id = resolve_ltm_scope(event, ltm_cfg=ltm_cfg)

            # Record user message
            if event.message_str:
                await ltm.record_conversation_event(
                    scope=scope,
                    scope_id=scope_id,
                    role="user",
                    text=event.message_str,
                    platform_id=event.get_platform_id() if hasattr(event, "get_platform_id") else None,
                    session_id=event.session_id if hasattr(event, "session_id") else None,
                )

            # Record assistant response
            if llm_response and llm_response.completion_text:
                await ltm.record_conversation_event(
                    scope=scope,
                    scope_id=scope_id,
                    role="assistant",
                    text=llm_response.completion_text,
                    platform_id=event.get_platform_id() if hasattr(event, "get_platform_id") else None,
                    session_id=event.session_id if hasattr(event, "session_id") else None,
                )

            # Schedule async extraction
            write_cfg = ltm_cfg.get("write_policy", {})
            if write_cfg.get("enable", True):
                from astrbot.core.long_term_memory.policy import MemoryWritePolicy

                write_policy = MemoryWritePolicy.from_dict(write_cfg)
                retention = ltm_cfg.get("retention_days", None)

                # Get provider for extraction
                extraction_provider_id = ltm_cfg.get("extraction_provider_id", "")
                plugin_context = run_context.context.context
                if extraction_provider_id and hasattr(plugin_context, "get_provider_by_id"):
                    provider = plugin_context.get_provider_by_id(extraction_provider_id)
                elif hasattr(plugin_context, "get_using_provider"):
                    provider = plugin_context.get_using_provider(
                        umo=event.unified_msg_origin
                    )
                else:
                    provider = None

                if provider:
                    ltm.schedule_extraction(
                        provider=provider,
                        write_policy=write_policy,
                        retention_days=retention,
                    )
        except Exception as e:
            logger.debug("LTM on_agent_done recording failed: %s", e)

    async def on_tool_start(
        self,
        run_context: ContextWrapper[AstrAgentContext],
        tool: FunctionTool[Any],
        tool_args: dict | None,
    ) -> None:
        await call_event_hook(
            run_context.context.event,
            EventType.OnUsingLLMToolEvent,
            tool,
            tool_args,
        )

    async def on_tool_end(
        self,
        run_context: ContextWrapper[AstrAgentContext],
        tool: FunctionTool[Any],
        tool_args: dict | None,
        tool_result: CallToolResult | None,
    ) -> None:
        run_context.context.event.clear_result()
        await call_event_hook(
            run_context.context.event,
            EventType.OnLLMToolRespondEvent,
            tool,
            tool_args,
            tool_result,
        )

        # special handle web_search_tavily
        platform_name = run_context.context.event.get_platform_name()
        if (
            platform_name == "webchat"
            and tool.name in ["web_search_tavily", "web_search_bocha"]
            and len(run_context.messages) > 0
            and tool_result
            and len(tool_result.content)
        ):
            # inject system prompt
            first_part = run_context.messages[0]
            if (
                isinstance(first_part, Message)
                and first_part.role == "system"
                and first_part.content
                and isinstance(first_part.content, str)
            ):
                # we assume system part is str
                first_part.content += (
                    "Always cite web search results you rely on. "
                    "Index is a unique identifier for each search result. "
                    "Use the exact citation format <ref>index</ref> (e.g. <ref>abcd.3</ref>) "
                    "after the sentence that uses the information. Do not invent citations."
                )

        # Record tool event for LTM
        try:
            from astrbot.core.long_term_memory.manager import get_ltm_manager

            ltm = get_ltm_manager()
            if ltm is None:
                return

            event = run_context.context.event
            ltm_cfg = _get_ltm_config(run_context)
            if not ltm_cfg or not ltm_cfg.get("enable", False):
                return
            if ltm_cfg.get("emergency_read_only", False):
                return

            scope, scope_id = resolve_ltm_scope(event, ltm_cfg=ltm_cfg)

            # Extract text result from tool_result
            result_text = None
            if tool_result and tool_result.content:
                for part in tool_result.content:
                    if isinstance(part, TextContent):
                        result_text = part.text[:500]
                        break

            await ltm.record_tool_event(
                scope=scope,
                scope_id=scope_id,
                tool_name=tool.name,
                tool_args=tool_args,
                tool_result=result_text,
                platform_id=event.get_platform_id() if hasattr(event, "get_platform_id") else None,
                session_id=event.session_id if hasattr(event, "session_id") else None,
            )
        except Exception as e:
            logger.debug("LTM on_tool_end recording failed: %s", e)


class EmptyAgentHooks(BaseAgentRunHooks[AstrAgentContext]):
    pass


MAIN_AGENT_HOOKS = MainAgentHooks()

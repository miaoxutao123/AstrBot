"""
Workflow Provider - Executes saved workflows as a provider.
"""

from collections.abc import AsyncGenerator

from astrbot import logger
from astrbot.core.agent.message import Message
from astrbot.core.agent.runners.workflow_agent_runner import (
    WorkflowAgentRunner,
    WorkflowResult,
)
from astrbot.core.agent.tool import ToolSet
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider.entities import LLMResponse, ToolCallsResult
from astrbot.core.provider.provider import Provider
from astrbot.core.provider.register import register_provider_adapter


@register_provider_adapter(
    "workflow",
    "工作流 Provider - 执行已保存的可视化工作流",
    provider_display_name="Workflow",
)
class WorkflowProvider(Provider):
    """
    Provider that executes a saved workflow.
    The workflow_id is specified in the provider config.
    """

    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        super().__init__(provider_config, provider_settings)

        self.workflow_id = provider_config.get("workflow_id", "")
        self.workflow_name = provider_config.get("workflow_name", "Workflow")
        self.workflow_data = provider_config.get("workflow_data", {})

        # These will be injected by the provider manager
        self._provider_manager = None
        self._kb_manager = None

        self.set_model(self.workflow_name)

    def set_managers(self, provider_manager, kb_manager):
        """Set the provider manager and knowledge base manager for workflow execution."""
        self._provider_manager = provider_manager
        self._kb_manager = kb_manager

    def get_current_key(self) -> str:
        return ""

    def set_key(self, key: str):
        pass

    async def get_models(self) -> list[str]:
        """Return the workflow name as the model."""
        return [self.workflow_name]

    async def text_chat(
        self,
        prompt: str | None = None,
        session_id: str | None = None,
        image_urls: list[str] | None = None,
        func_tool: ToolSet | None = None,
        contexts: list[Message] | list[dict] | None = None,
        system_prompt: str | None = None,
        tool_calls_result: ToolCallsResult | list[ToolCallsResult] | None = None,
        model: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Execute the workflow with the given prompt."""

        # Extract user input from prompt or contexts
        user_input = ""
        if prompt:
            user_input = prompt
        elif contexts:
            # Get the last user message
            for ctx in reversed(contexts):
                if isinstance(ctx, dict):
                    if ctx.get("role") == "user":
                        content = ctx.get("content", "")
                        if isinstance(content, str):
                            user_input = content
                        elif isinstance(content, list):
                            # Handle multimodal content
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    user_input = item.get("text", "")
                                    break
                        break
                elif isinstance(ctx, Message) and ctx.role == "user":
                    # Handle Message object
                    content = ctx.content
                    if isinstance(content, str):
                        user_input = content
                    elif isinstance(content, list):
                        # Handle multimodal content (list of ContentPart)
                        for part in content:
                            if hasattr(part, "text"):
                                user_input = part.text
                                break
                            elif hasattr(part, "type") and part.type == "text":
                                user_input = getattr(part, "text", "")
                                break
                    break
                elif hasattr(ctx, "role") and ctx.role == "user":
                    # Fallback for other objects with role attribute
                    content = getattr(ctx, "content", None)
                    if isinstance(content, str):
                        user_input = content
                    elif content:
                        user_input = str(content)
                    break

        if not user_input:
            logger.warning("WorkflowProvider: No input provided, contexts may be empty or no user message found")
            return LLMResponse(
                role="assistant",
                result_chain=MessageChain().message("No input provided"),
            )

        if not self._provider_manager:
            logger.error("WorkflowProvider: Provider manager not initialized")
            return LLMResponse(
                role="assistant",
                result_chain=MessageChain().message(
                    "Workflow provider not properly initialized"
                ),
            )

        logger.info(f"WorkflowProvider: Executing workflow with input: {user_input[:100]}...")

        # Execute the workflow
        try:
            runner = WorkflowAgentRunner(
                workflow_data=self.workflow_data,
                provider_manager=self._provider_manager,
                kb_manager=self._kb_manager,
            )

            result: WorkflowResult = await runner.run(user_input)

            if result.success:
                logger.info(f"WorkflowProvider: Workflow completed successfully, result length: {len(result.result_text)}")
                return LLMResponse(
                    role="assistant",
                    result_chain=MessageChain().message(result.result_text),
                )
            else:
                error_msg = f"Workflow execution failed: {result.error}"
                logger.error(error_msg)
                return LLMResponse(
                    role="assistant",
                    result_chain=MessageChain().message(error_msg),
                )

        except Exception as e:
            error_msg = f"Workflow execution error: {e}"
            logger.error(error_msg, exc_info=True)
            return LLMResponse(
                role="assistant",
                result_chain=MessageChain().message(error_msg),
            )

    async def text_chat_stream(
        self,
        prompt: str | None = None,
        session_id: str | None = None,
        image_urls: list[str] | None = None,
        func_tool: ToolSet | None = None,
        contexts: list[Message] | list[dict] | None = None,
        system_prompt: str | None = None,
        tool_calls_result: ToolCallsResult | list[ToolCallsResult] | None = None,
        model: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[LLMResponse, None]:
        """
        Workflow doesn't support true streaming, so we just yield the final result.
        """
        result = await self.text_chat(
            prompt=prompt,
            session_id=session_id,
            image_urls=image_urls,
            func_tool=func_tool,
            contexts=contexts,
            system_prompt=system_prompt,
            tool_calls_result=tool_calls_result,
            model=model,
            **kwargs,
        )
        yield result

    async def test(self):
        """Test that the workflow is valid."""
        if not self.workflow_data:
            raise ValueError("No workflow data configured")

        nodes = self.workflow_data.get("nodes", [])
        if not nodes:
            raise ValueError("Workflow has no nodes")

        has_start = any(n.get("type") == "start" for n in nodes)
        has_end = any(n.get("type") == "end" for n in nodes)

        if not has_start:
            raise ValueError("Workflow has no start node")
        if not has_end:
            raise ValueError("Workflow has no end node")

        return True

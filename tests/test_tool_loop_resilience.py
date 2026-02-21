import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from astrbot.core.agent.hooks import BaseAgentRunHooks
from astrbot.core.agent.message import ImageURLPart, Message, TextPart
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.agent.tool_executor import BaseFunctionToolExecutor
from astrbot.core.provider.entities import LLMResponse, ProviderRequest, TokenUsage
from astrbot.core.provider.provider import Provider


class FlakyProvider(Provider):
    def __init__(self, fail_times: int = 1):
        super().__init__({}, {})
        self.fail_times = fail_times
        self.call_count = 0

    def get_current_key(self) -> str:
        return "test-key"

    def set_key(self, key: str):
        return None

    async def get_models(self) -> list[str]:
        return ["test-model"]

    async def text_chat(self, **kwargs) -> LLMResponse:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise RuntimeError("connection reset by peer")

        return LLMResponse(
            role="assistant",
            completion_text="Recovered after retry",
            usage=TokenUsage(input_other=10, output=4),
        )

    async def text_chat_stream(self, **kwargs):
        response = await self.text_chat(**kwargs)
        response.is_chunk = False
        yield response


class DummyToolExecutor(BaseFunctionToolExecutor):
    @classmethod
    async def execute(cls, tool, run_context, **tool_args):  # pragma: no cover
        yield None


@pytest.mark.asyncio
async def test_tool_loop_runner_auto_retry_on_transient_provider_error():
    runner = ToolLoopAgentRunner()
    provider = FlakyProvider(fail_times=1)
    request = ProviderRequest(prompt="hello", contexts=[])

    await runner.reset(
        provider=provider,
        request=request,
        run_context=ContextWrapper(context=None),
        tool_executor=DummyToolExecutor(),
        agent_hooks=BaseAgentRunHooks(),
        streaming=False,
    )

    responses = []
    async for response in runner.step_until_done(max_step=3):
        responses.append(response)

    assert runner.done()
    assert provider.call_count == 2
    assert any(resp.type == "llm_result" for resp in responses)


class OverflowThenRecoverProvider(Provider):
    def __init__(self):
        super().__init__({}, {})
        self.call_count = 0
        self.context_sizes: list[int] = []

    def get_current_key(self) -> str:
        return "test-key"

    def set_key(self, key: str):
        return None

    async def get_models(self) -> list[str]:
        return ["test-model"]

    def _estimate_context_chars(self, contexts) -> int:
        total = 0
        for msg in contexts or []:
            content = getattr(msg, "content", None)
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                for part in content:
                    total += len(str(part))
        return total

    async def text_chat(self, **kwargs) -> LLMResponse:
        self.call_count += 1
        contexts = kwargs.get("contexts") or []
        self.context_sizes.append(self._estimate_context_chars(contexts))

        if self.call_count == 1:
            raise RuntimeError(
                "The input token count exceeds the maximum number of tokens allowed 1048576."
            )

        return LLMResponse(
            role="assistant",
            completion_text="Recovered after context trim",
            usage=TokenUsage(input_other=8, output=4),
        )

    async def text_chat_stream(self, **kwargs):
        response = await self.text_chat(**kwargs)
        response.is_chunk = False
        yield response


class SchemaSensitiveOverflowProvider(Provider):
    def __init__(self):
        super().__init__({}, {})
        self.call_count = 0
        self.schema_sizes: list[int] = []

    def get_current_key(self) -> str:
        return "test-key"

    def set_key(self, key: str):
        return None

    async def get_models(self) -> list[str]:
        return ["test-model"]

    async def text_chat(self, **kwargs) -> LLMResponse:
        self.call_count += 1
        func_tool = kwargs.get("func_tool")
        if isinstance(func_tool, ToolSet):
            schema_size = len(json.dumps(func_tool.openai_schema(), ensure_ascii=False))
        else:
            schema_size = 0
        self.schema_sizes.append(schema_size)

        if schema_size > 400:
            raise RuntimeError(
                "The input token count exceeds the maximum number of tokens allowed 1048576."
            )

        return LLMResponse(
            role="assistant",
            completion_text="Recovered after tool-schema compaction",
            usage=TokenUsage(input_other=8, output=4),
        )

    async def text_chat_stream(self, **kwargs):
        response = await self.text_chat(**kwargs)
        response.is_chunk = False
        yield response


@pytest.mark.asyncio
async def test_tool_loop_runner_auto_trim_on_context_overflow_error():
    runner = ToolLoopAgentRunner()
    provider = OverflowThenRecoverProvider()
    request = ProviderRequest(prompt="x" * 400000, contexts=[])

    await runner.reset(
        provider=provider,
        request=request,
        run_context=ContextWrapper(context=None),
        tool_executor=DummyToolExecutor(),
        agent_hooks=BaseAgentRunHooks(),
        streaming=False,
    )

    responses = []
    async for response in runner.step_until_done(max_step=3):
        responses.append(response)

    assert runner.done()
    assert provider.call_count == 2
    assert len(provider.context_sizes) >= 2
    assert provider.context_sizes[1] <= provider.context_sizes[0]
    assert any(resp.type == "llm_result" for resp in responses)


@pytest.mark.asyncio
async def test_tool_loop_runner_compacts_tool_schema_after_overflow_error():
    runner = ToolLoopAgentRunner()
    provider = SchemaSensitiveOverflowProvider()

    tool = FunctionTool(
        name="heavy_tool",
        description="heavy tool",
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "string",
                    "description": "X" * 6000,
                }
            },
        },
    )
    request = ProviderRequest(
        prompt="trigger tool-schema overflow recovery",
        contexts=[],
        func_tool=ToolSet([tool]),
    )

    await runner.reset(
        provider=provider,
        request=request,
        run_context=ContextWrapper(context=None),
        tool_executor=DummyToolExecutor(),
        agent_hooks=BaseAgentRunHooks(),
        streaming=False,
    )

    responses = []
    async for response in runner.step_until_done(max_step=3):
        responses.append(response)

    assert runner.done()
    assert provider.call_count >= 2
    assert len(provider.schema_sizes) >= 2
    assert provider.schema_sizes[0] > 400
    assert provider.schema_sizes[1] < provider.schema_sizes[0]
    assert any(resp.type == "llm_result" for resp in responses)


def test_tool_result_sanitizer_compacts_block_page():
    runner = ToolLoopAgentRunner()
    runner.run_context = ContextWrapper(context=None)

    payload = (
        "<!DOCTYPE html><html><body>请求携带恶意参数 已被拦截 by 1Panel</body></html>"
        + ("A" * 20000)
    )

    compact = runner._sanitize_tool_result_for_context(payload, max_chars=3000)

    assert "raw HTML error page omitted" in compact
    assert len(compact) <= 3000


def test_trim_message_keeps_valid_data_url_and_replaces_truncated_data_url():
    runner = ToolLoopAgentRunner()
    runner.run_context = ContextWrapper(context=None)

    valid_data_url = "data:image/png;base64," + ("A" * 20000)
    valid_message = Message(
        role="user",
        content=[
            ImageURLPart(
                image_url=ImageURLPart.ImageURL(url=valid_data_url),
            )
        ],
    )
    changed = runner._trim_message_for_context(valid_message, max_message_chars=12000)
    assert changed is False
    assert isinstance(valid_message.content, list)
    assert isinstance(valid_message.content[0], ImageURLPart)
    assert valid_message.content[0].image_url.url == valid_data_url

    truncated_data_url = "data:image/jpeg;base64,AAA\n...[truncated 100 chars]...\nBBB"
    broken_message = Message(
        role="user",
        content=[
            ImageURLPart(
                image_url=ImageURLPart.ImageURL(url=truncated_data_url),
            )
        ],
    )
    changed = runner._trim_message_for_context(broken_message, max_message_chars=12000)
    assert changed is True
    assert isinstance(broken_message.content, list)
    assert isinstance(broken_message.content[0], TextPart)
    assert broken_message.content[0].text == "[图片内容已省略]"

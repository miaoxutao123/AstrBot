import asyncio
import copy
import json
import re
import sys
import time
import traceback
import typing as T
from dataclasses import dataclass, field

from mcp.types import (
    BlobResourceContents,
    CallToolResult,
    EmbeddedResource,
    ImageContent,
    TextContent,
    TextResourceContents,
)

from astrbot import logger
from astrbot.core.agent.message import ImageURLPart, TextPart, ThinkPart
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.agent.tool_image_cache import tool_image_cache
from astrbot.core.message.components import Json
from astrbot.core.message.message_event_result import (
    MessageChain,
)
from astrbot.core.provider.entities import (
    LLMResponse,
    ProviderRequest,
    ToolCallsResult,
)
from astrbot.core.provider.provider import Provider

from ...runtime.resilience_monitor import coding_resilience_monitor
from ...tool_evolution.manager import tool_evolution_manager
from ..context.compressor import ContextCompressor
from ..context.config import ContextConfig
from ..context.manager import ContextManager
from ..context.token_counter import TokenCounter
from ..hooks import BaseAgentRunHooks
from ..message import AssistantMessageSegment, Message, ToolCallMessageSegment
from ..response import AgentResponseData, AgentStats
from ..run_context import ContextWrapper, TContext
from ..tool_executor import BaseFunctionToolExecutor
from .base import AgentResponse, AgentState, BaseAgentRunner

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override


@dataclass(slots=True)
class _HandleFunctionToolsResult:
    kind: T.Literal["message_chain", "tool_call_result_blocks", "cached_image"]
    message_chain: MessageChain | None = None
    tool_call_result_blocks: list[ToolCallMessageSegment] | None = None
    cached_image: T.Any = None

    @classmethod
    def from_message_chain(cls, chain: MessageChain) -> "_HandleFunctionToolsResult":
        return cls(kind="message_chain", message_chain=chain)

    @classmethod
    def from_tool_call_result_blocks(
        cls, blocks: list[ToolCallMessageSegment]
    ) -> "_HandleFunctionToolsResult":
        return cls(kind="tool_call_result_blocks", tool_call_result_blocks=blocks)

    @classmethod
    def from_cached_image(cls, image: T.Any) -> "_HandleFunctionToolsResult":
        return cls(kind="cached_image", cached_image=image)


@dataclass(slots=True)
class FollowUpTicket:
    """Ticket used by pipeline follow-up coordinator."""

    seq: int
    text: str
    resolved: asyncio.Event = field(default_factory=asyncio.Event)
    consumed: bool = False

    def resolve(self, consumed: bool = False) -> None:
        self.consumed = consumed
        self.resolved.set()

_TRANSIENT_PROVIDER_ERROR_HINTS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "connection refused",
    "temporarily unavailable",
    "service unavailable",
    "rate limit",
    "too many requests",
    "quota",
    "429",
    "500",
    "502",
    "503",
    "504",
    "api error",
    "network",
)

_CONTEXT_OVERFLOW_ERROR_HINTS = (
    "input token count exceeds",
    "maximum number of tokens allowed",
    "maximum context length",
    "context length exceeded",
    "context_length_exceeded",
    "too many tokens",
)

_UNCERTAIN_ANSWER_HINTS = (
    "不确定",
    "不知道",
    "不清楚",
    "无法确认",
    "记不清",
    "不能确定",
    "无法判断",
    "not sure",
    "don't know",
    "do not know",
    "unclear",
    "cannot determine",
    "can't recall",
    "cannot recall",
)

_MEMORY_RECALL_QUERY_HINTS = (
    "生日",
    "年龄",
    "几岁",
    "名字",
    "叫什么",
    "昵称",
    "偏好",
    "喜欢",
    "住在",
    "城市",
    "地址",
    "电话",
    "邮箱",
    "职业",
    "工作",
    "学校",
    "爱好",
    "记得",
    "回忆",
    "birthday",
    "age",
    "name",
    "nickname",
    "preference",
    "prefer",
    "city",
    "address",
    "phone",
    "email",
    "occupation",
    "job",
    "remember",
    "recall",
)

_INFO_REQUEST_HINTS = (
    "请提供",
    "请告诉",
    "告诉我更多",
    "提供更多",
    "补充信息",
    "需要更多信息",
    "please provide",
    "provide more",
    "share more details",
    "need more information",
)

_LACK_OF_INFO_HINTS = (
    "没有记录",
    "没有相关",
    "未找到",
    "无法找到",
    "查不到",
    "没有足够信息",
    "信息不足",
    "can't find",
    "cannot find",
    "not found",
    "no record",
    "no relevant memory",
    "insufficient info",
)

_LARGE_DATA_URL_RE = re.compile(r"data:[^\s'\"<>)]{80,}", re.IGNORECASE)
_LARGE_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
_LARGE_HEX_RE = re.compile(r"[0-9a-fA-F]{200,}")


class ToolLoopAgentRunner(BaseAgentRunner[TContext]):
    @override
    async def reset(
        self,
        provider: Provider,
        request: ProviderRequest,
        run_context: ContextWrapper[TContext],
        tool_executor: BaseFunctionToolExecutor[TContext],
        agent_hooks: BaseAgentRunHooks[TContext],
        streaming: bool = False,
        # enforce max turns, will discard older turns when exceeded BEFORE compression
        # -1 means no limit
        enforce_max_turns: int = -1,
        # llm compressor
        llm_compress_instruction: str | None = None,
        llm_compress_keep_recent: int = 0,
        llm_compress_provider: Provider | None = None,
        # truncate by turns compressor
        truncate_turns: int = 1,
        # customize
        custom_token_counter: TokenCounter | None = None,
        custom_compressor: ContextCompressor | None = None,
        tool_schema_mode: str | None = "full",
        fallback_providers: list[Provider] | None = None,
        **kwargs: T.Any,
    ) -> None:
        self.req = request
        self.streaming = streaming
        self.enforce_max_turns = enforce_max_turns
        self.llm_compress_instruction = llm_compress_instruction
        self.llm_compress_keep_recent = llm_compress_keep_recent
        self.llm_compress_provider = llm_compress_provider
        self.truncate_turns = truncate_turns
        self.custom_token_counter = custom_token_counter
        self.custom_compressor = custom_compressor
        # we will do compress when:
        # 1. before requesting LLM
        # TODO: 2. after LLM output a tool call
        self.context_config = ContextConfig(
            # <=0 will never do compress
            max_context_tokens=provider.provider_config.get("max_context_tokens", 0),
            # enforce max turns before compression
            enforce_max_turns=self.enforce_max_turns,
            truncate_turns=self.truncate_turns,
            llm_compress_instruction=self.llm_compress_instruction,
            llm_compress_keep_recent=self.llm_compress_keep_recent,
            llm_compress_provider=self.llm_compress_provider,
            custom_token_counter=self.custom_token_counter,
            custom_compressor=self.custom_compressor,
        )
        self.context_manager = ContextManager(self.context_config)

        self.provider = provider
        self.fallback_providers: list[Provider] = []
        seen_provider_ids: set[str] = {str(provider.provider_config.get("id", ""))}
        for fallback_provider in fallback_providers or []:
            fallback_id = str(fallback_provider.provider_config.get("id", ""))
            if fallback_provider is provider:
                continue
            if fallback_id and fallback_id in seen_provider_ids:
                continue
            self.fallback_providers.append(fallback_provider)
            if fallback_id:
                seen_provider_ids.add(fallback_id)
        self.final_llm_resp = None
        self._state = AgentState.IDLE
        self.tool_executor = tool_executor
        self.agent_hooks = agent_hooks
        self.run_context = run_context

        # These two are used for tool schema mode handling
        # We now have two modes:
        # - "full": use full tool schema for LLM calls, default.
        # - "skills_like": use light tool schema for LLM calls, and re-query with param-only schema when needed.
        #   Light tool schema does not include tool parameters.
        #   This can reduce token usage when tools have large descriptions.
        # See #4681
        self.tool_schema_mode = tool_schema_mode
        self._tool_schema_param_set = None
        self._skill_like_raw_tool_set = None
        self._runtime_force_skills_like = False
        if tool_schema_mode == "skills_like":
            tool_set = self.req.func_tool
            if tool_set:
                self._skill_like_raw_tool_set = tool_set
                light_set = tool_set.get_light_tool_set()
                self._tool_schema_param_set = tool_set.get_param_only_tool_set()
                # MODIFIE the req.func_tool to use light tool schemas
                self.req.func_tool = light_set

        messages = []
        # append existing messages in the run context
        for msg in request.contexts:
            m = Message.model_validate(msg)
            if isinstance(msg, dict) and msg.get("_no_save"):
                m._no_save = True
            messages.append(m)
        if request.prompt is not None:
            m = await request.assemble_context()
            messages.append(Message.model_validate(m))
        if request.system_prompt:
            messages.insert(
                0,
                Message(role="system", content=request.system_prompt),
            )
        self.run_context.messages = messages

        self.stats = AgentStats()
        self.stats.start_time = time.time()
        self._follow_up_seq = 0

    def follow_up(self, message_text: str) -> FollowUpTicket | None:
        """Capture a follow-up message for compatibility with pipeline follow-up stage.

        Current runner behavior is to let the follow-up continue as the next normal turn
        (not in-band consumed by current run), so the ticket is resolved immediately with
        consumed=False.
        """
        text = (message_text or "").strip()
        if not text:
            return None

        seq = int(getattr(self, "_follow_up_seq", 0))
        self._follow_up_seq = seq + 1
        ticket = FollowUpTicket(seq=seq, text=text)
        ticket.resolve(consumed=False)
        return ticket

    def _get_tool_evolution_cfg(self) -> dict[str, T.Any]:
        astr_context = getattr(self.run_context, "context", None)
        if astr_context is None:
            return {}

        plugin_context = getattr(astr_context, "context", None)
        if plugin_context is None or not hasattr(plugin_context, "get_config"):
            return {}

        event = getattr(astr_context, "event", None)
        try:
            if event is not None and hasattr(event, "unified_msg_origin"):
                cfg = plugin_context.get_config(umo=event.unified_msg_origin)
            else:
                cfg = plugin_context.get_config()
        except Exception:
            return {}

        if not isinstance(cfg, dict):
            return {}
        provider_settings = cfg.get("provider_settings")
        if not isinstance(provider_settings, dict):
            return {}
        evo_cfg = provider_settings.get("tool_evolution", {})
        return evo_cfg if isinstance(evo_cfg, dict) else {}

    def _get_runtime_resilience_cfg(self) -> dict[str, T.Any]:
        astr_context = getattr(self.run_context, "context", None)
        if astr_context is None:
            return {}

        plugin_context = getattr(astr_context, "context", None)
        if plugin_context is None or not hasattr(plugin_context, "get_config"):
            return {}

        event = getattr(astr_context, "event", None)
        try:
            if event is not None and hasattr(event, "unified_msg_origin"):
                cfg = plugin_context.get_config(umo=event.unified_msg_origin)
            else:
                cfg = plugin_context.get_config()
        except Exception:
            return {}

        if not isinstance(cfg, dict):
            return {}
        provider_settings = cfg.get("provider_settings")
        if not isinstance(provider_settings, dict):
            return {}
        resilience_cfg = provider_settings.get("coding_resilience", {})
        return resilience_cfg if isinstance(resilience_cfg, dict) else {}

    def _get_ltm_cfg(self) -> dict[str, T.Any]:
        astr_context = getattr(self.run_context, "context", None)
        if astr_context is None:
            return {}

        plugin_context = getattr(astr_context, "context", None)
        if plugin_context is None or not hasattr(plugin_context, "get_config"):
            return {}

        event = getattr(astr_context, "event", None)
        try:
            if event is not None and hasattr(event, "unified_msg_origin"):
                cfg = plugin_context.get_config(umo=event.unified_msg_origin)
            else:
                cfg = plugin_context.get_config()
        except Exception:
            return {}

        if not isinstance(cfg, dict):
            return {}

        ltm_settings = cfg.get("provider_ltm_settings", {})
        if not isinstance(ltm_settings, dict):
            return {}
        ltm_cfg = ltm_settings.get("long_term_memory", {})
        return ltm_cfg if isinstance(ltm_cfg, dict) else {}

    def _is_transient_provider_error(self, err: Exception | str) -> bool:
        text = str(err).lower().strip()
        if not text:
            return False
        return any(hint in text for hint in _TRANSIENT_PROVIDER_ERROR_HINTS)

    def _is_context_overflow_error(self, err: Exception | str) -> bool:
        text = str(err).lower().strip()
        if not text:
            return False
        return any(hint in text for hint in _CONTEXT_OVERFLOW_ERROR_HINTS)

    def _cfg_int(self, cfg: dict[str, T.Any], key: str, default: int) -> int:
        try:
            value = int(cfg.get(key, default) or default)
        except Exception:
            value = default
        return value

    def _clip_text_for_context(self, text: str, *, max_chars: int) -> str:
        if max_chars <= 0:
            return ""
        value = str(text or "")
        if len(value) <= max_chars:
            return value

        head = max(80, int(max_chars * 0.66))
        tail = max(40, max_chars - head - 80)
        if head + tail >= len(value):
            return value[:max_chars]
        omitted = len(value) - head - tail
        return f"{value[:head]}\n...[truncated {omitted} chars]...\n{value[-tail:]}"

    def _is_uncertain_answer(self, text: str | None) -> bool:
        value = str(text or "").strip().lower()
        if not value:
            return False
        return any(hint in value for hint in _UNCERTAIN_ANSWER_HINTS)

    @staticmethod
    def _contains_any_fragment(text: str, fragments: tuple[str, ...]) -> bool:
        value = str(text or "")
        if not value:
            return False
        return any(fragment in value for fragment in fragments if fragment)

    def _is_memory_recall_query(self, query_text: str | None) -> bool:
        query = str(query_text or "").strip().lower()
        if not query:
            return False
        return self._contains_any_fragment(query, _MEMORY_RECALL_QUERY_HINTS)

    def _looks_like_fact_answer(self, answer_text: str | None) -> bool:
        answer = str(answer_text or "").strip()
        if not answer:
            return False

        # Date/time-like explicit values.
        if re.search(r"\d{4}\s*[年/-]\s*\d{1,2}\s*[月/-]\s*\d{1,2}", answer):
            return True
        # Basic contact-like values.
        if re.search(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", answer):
            return True
        if re.search(r"\b\d{3,4}[-\s]?\d{3,4}[-\s]?\d{3,4}\b", answer):
            return True
        # Declarative fact patterns.
        if re.search(
            r"(生日|名字|昵称|偏好|住在|城市|地址|电话|邮箱|职业|年龄).{0,16}(是|为|：|:)",
            answer,
        ):
            return True
        if re.search(r"\b(your|you)\s+\w{2,24}\s+(is|are)\b", answer.lower()):
            return True
        return False

    def _post_think_uncertainty_score(
        self,
        *,
        query_text: str | None,
        answer_text: str | None,
        reasoning_text: str | None,
    ) -> int:
        answer = str(answer_text or "").strip().lower()
        reasoning = str(reasoning_text or "").strip().lower()
        query = str(query_text or "").strip().lower()

        if not answer:
            return 10

        score = 0
        if self._is_uncertain_answer(answer):
            score += 3
        if reasoning and self._is_uncertain_answer(reasoning):
            score += 2
        if self._contains_any_fragment(answer, _INFO_REQUEST_HINTS):
            score += 2
        if self._contains_any_fragment(answer, _LACK_OF_INFO_HINTS):
            score += 2

        memory_query = self._is_memory_recall_query(query)
        if memory_query:
            score += 1
            if len(answer) <= 64:
                score += 1
            if not self._looks_like_fact_answer(answer):
                score += 1

        if self._looks_like_fact_answer(answer):
            score -= 2
        elif len(answer) >= 240:
            score -= 1

        return max(0, score)

    def _extract_user_query_text(self) -> str:
        astr_context = getattr(self.run_context, "context", None)
        event = getattr(astr_context, "event", None) if astr_context is not None else None
        message_text = getattr(event, "message_str", None)
        if isinstance(message_text, str) and message_text.strip():
            return message_text.strip()

        for msg in reversed(self.run_context.messages or []):
            if msg.role != "user":
                continue
            content = msg.content
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, TextPart) and part.text:
                        parts.append(part.text)
                joined = " ".join(parts).strip()
                if joined:
                    return joined
        return ""

    async def _maybe_post_think_recall(
        self,
        llm_resp: LLMResponse,
    ) -> LLMResponse:
        """Second-pass memory recall after draft answer for uncertainty cases."""
        if self.streaming:
            return llm_resp
        if llm_resp.role != "assistant":
            return llm_resp
        if llm_resp.tools_call_name:
            return llm_resp

        ltm_cfg = self._get_ltm_cfg()
        if not ltm_cfg or not bool(ltm_cfg.get("enable", False)):
            return llm_resp

        read_cfg = ltm_cfg.get("read_policy", {})
        if not isinstance(read_cfg, dict) or not bool(read_cfg.get("enable", True)):
            return llm_resp
        if not bool(read_cfg.get("post_think_recall_enable", False)):
            return llm_resp

        user_query_text = self._extract_user_query_text()
        only_on_uncertain = bool(read_cfg.get("post_think_recall_only_on_uncertain", True))
        if only_on_uncertain:
            score = self._post_think_uncertainty_score(
                query_text=user_query_text,
                answer_text=llm_resp.completion_text,
                reasoning_text=llm_resp.reasoning_content,
            )
            threshold = max(
                1,
                self._cfg_int(read_cfg, "post_think_recall_uncertainty_threshold", 3),
            )
            if score < threshold:
                return llm_resp

        try:
            from astrbot.core.long_term_memory.manager import get_ltm_manager
            from astrbot.core.long_term_memory.policy import MemoryReadPolicy
            from astrbot.core.long_term_memory.scope import resolve_ltm_read_targets
        except Exception:
            return llm_resp

        ltm = get_ltm_manager()
        if ltm is None:
            return llm_resp

        astr_context = getattr(self.run_context, "context", None)
        event = getattr(astr_context, "event", None) if astr_context is not None else None
        plugin_context = getattr(astr_context, "context", None) if astr_context is not None else None
        if event is None:
            return llm_resp

        try:
            scope, scope_id, additional_scopes = resolve_ltm_read_targets(event, ltm_cfg=ltm_cfg)
        except Exception:
            return llm_resp

        recall_policy = MemoryReadPolicy.from_dict(read_cfg)
        recall_policy.max_items = min(
            recall_policy.max_items,
            max(1, self._cfg_int(read_cfg, "post_think_recall_max_items", 8)),
        )
        recall_policy.max_tokens = min(
            recall_policy.max_tokens,
            max(120, self._cfg_int(read_cfg, "post_think_recall_max_tokens", 400)),
        )
        recall_policy.include_relations = bool(
            read_cfg.get("post_think_recall_include_relations", recall_policy.include_relations)
        )
        if read_cfg.get("post_think_recall_relation_only_mode") is not None:
            recall_policy.relation_only_mode = bool(
                read_cfg.get("post_think_recall_relation_only_mode")
            )

        embedding_provider = None
        embedding_provider_id = str(ltm_cfg.get("embedding_provider_id", "") or "").strip()
        if (
            embedding_provider_id
            and plugin_context is not None
            and hasattr(plugin_context, "get_provider_by_id")
        ):
            provider = plugin_context.get_provider_by_id(embedding_provider_id)
            if provider is not None and hasattr(provider, "get_embedding"):
                embedding_provider = provider

        max_query_chars = max(
            120,
            self._cfg_int(read_cfg, "post_think_recall_max_query_chars", 600),
        )
        query_parts = [
            user_query_text,
            str(llm_resp.completion_text or ""),
            str(llm_resp.reasoning_content or ""),
        ]
        recall_query = self._clip_text_for_context(
            "\n".join(part for part in query_parts if part),
            max_chars=max_query_chars,
        )
        if not recall_query.strip():
            return llm_resp

        try:
            memory_context = await ltm.retrieve_memory_context(
                scope=scope,
                scope_id=scope_id,
                read_policy=recall_policy,
                query_text=recall_query,
                additional_scopes=additional_scopes,
                embedding_provider=embedding_provider,
            )
        except Exception:
            return llm_resp

        if not memory_context:
            return llm_resp

        draft_limit = max(200, self._cfg_int(read_cfg, "post_think_recall_max_draft_chars", 1200))
        draft_answer = self._clip_text_for_context(
            str(llm_resp.completion_text or ""),
            max_chars=draft_limit,
        )
        refine_prompt = (
            "你已经给出了第一版回答。请仅在相关时使用下面补充的长期记忆修正答案。\n"
            f"<draft_answer>\n{draft_answer}\n</draft_answer>\n"
            f"{memory_context}\n"
            "输出要求：仅输出最终回答；若补充记忆不相关，保持原答案核心。"
        )

        try:
            refined = await self.provider.text_chat(
                contexts=self.run_context.messages,
                prompt=refine_prompt,
                func_tool=None,
                model=self.req.model,
                session_id=self.req.session_id,
            )
        except Exception:
            return llm_resp

        if refined is None or refined.role == "err" or refined.tools_call_name:
            return llm_resp
        if not str(refined.completion_text or "").strip():
            return llm_resp

        if refined.usage:
            self.stats.token_usage += refined.usage
            if self.req.conversation:
                self.req.conversation.token_usage = refined.usage.total
        return refined

    def _sanitize_tool_result_for_context(
        self,
        text: str,
        *,
        max_chars: int | None = None,
    ) -> str:
        resilience_cfg = self._get_runtime_resilience_cfg()
        limit = (
            self._cfg_int(resilience_cfg, "max_tool_result_chars", 12000)
            if max_chars is None
            else int(max_chars)
        )
        limit = max(800, min(limit, 50000))

        value = str(text or "")
        lowered = value.lower()
        if "<!doctype html" in lowered and (
            "请求携带恶意参数" in value
            or "malicious" in lowered
            or "1panel" in lowered
            or "cloudflare" in lowered
        ):
            value = (
                "error: upstream gateway blocked this payload as suspicious; "
                "raw HTML error page omitted to keep context compact. "
                "Try narrowing scope/path_prefix or reducing payload size."
            )

        value = _LARGE_DATA_URL_RE.sub("[[data_url_omitted]]", value)
        value = _LARGE_BASE64_RE.sub("[[base64_blob_omitted]]", value)
        value = _LARGE_HEX_RE.sub("[[hex_blob_omitted]]", value)
        value = value.replace("\r\n", "\n")
        value = re.sub(r"\n{4,}", "\n\n\n", value)

        return self._clip_text_for_context(value, max_chars=limit)

    def _approx_message_chars(self, msg: Message) -> int:
        total = 0

        content = msg.content
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, TextPart):
                    total += len(part.text)
                elif isinstance(part, ThinkPart):
                    total += len(part.think)
                else:
                    try:
                        total += len(str(part.model_dump()))
                    except Exception:
                        total += len(str(part))

        if msg.tool_calls:
            for tool_call in msg.tool_calls:
                try:
                    if hasattr(tool_call, "function"):
                        total += len(str(tool_call.function.arguments or ""))
                        total += len(str(tool_call.function.name or ""))
                    elif isinstance(tool_call, dict):
                        func = tool_call.get("function", {})
                        total += len(str(func.get("arguments", "") or ""))
                        total += len(str(func.get("name", "") or ""))
                except Exception:
                    total += len(str(tool_call))

        return total

    def _trim_message_for_context(
        self, msg: Message, *, max_message_chars: int
    ) -> bool:
        changed = False

        if isinstance(msg.content, str):
            trimmed = self._sanitize_tool_result_for_context(
                msg.content,
                max_chars=max_message_chars,
            )
            if trimmed != msg.content:
                msg.content = trimmed
                changed = True
        elif isinstance(msg.content, list):
            for idx, part in enumerate(msg.content):
                if isinstance(part, TextPart):
                    trimmed = self._sanitize_tool_result_for_context(
                        part.text,
                        max_chars=max_message_chars,
                    )
                    if trimmed != part.text:
                        part.text = trimmed
                        changed = True
                elif isinstance(part, ThinkPart):
                    trimmed = self._clip_text_for_context(
                        part.think,
                        max_chars=max(600, max_message_chars // 2),
                    )
                    if trimmed != part.think:
                        part.think = trimmed
                        changed = True
                elif hasattr(part, "image_url") and hasattr(part.image_url, "url"):
                    url = str(part.image_url.url or "")
                    # Do not truncate data URLs: truncation breaks base64 and can trigger provider 400.
                    if url.startswith("data:") and (
                        "[truncated " in url or "\n" in url or "\r" in url
                    ):
                        msg.content[idx] = TextPart(text="[图片内容已省略]")
                        changed = True

        if msg.tool_calls:
            for tool_call in msg.tool_calls:
                if hasattr(tool_call, "function") and hasattr(
                    tool_call.function, "arguments"
                ):
                    args = tool_call.function.arguments
                    # tool_call.arguments must remain valid JSON for OpenAI-compatible APIs.
                    # Do not inject truncation markers into arguments.
                    if isinstance(args, str) and len(args) > max_message_chars:
                        continue
                elif isinstance(tool_call, dict):
                    func = tool_call.get("function")
                    if isinstance(func, dict) and isinstance(
                        func.get("arguments"), str
                    ):
                        args = func["arguments"]
                        if len(args) > max_message_chars:
                            continue

        return changed

    def _apply_hard_context_size_guard(
        self,
        *,
        max_total_chars: int | None = None,
        max_message_chars: int | None = None,
        keep_recent_messages: int | None = None,
    ) -> bool:
        resilience_cfg = self._get_runtime_resilience_cfg()
        total_limit = (
            self._cfg_int(resilience_cfg, "max_total_context_chars", 250000)
            if max_total_chars is None
            else int(max_total_chars)
        )
        message_limit = (
            self._cfg_int(resilience_cfg, "max_message_chars", 12000)
            if max_message_chars is None
            else int(max_message_chars)
        )
        keep_recent = (
            self._cfg_int(resilience_cfg, "hard_keep_recent_messages", 14)
            if keep_recent_messages is None
            else int(keep_recent_messages)
        )

        total_limit = max(20000, min(total_limit, 2_000_000))
        message_limit = max(600, min(message_limit, 100000))
        keep_recent = max(4, min(keep_recent, 120))

        messages = self.run_context.messages or []
        if not messages:
            return False

        changed = False
        for msg in messages:
            changed = (
                self._trim_message_for_context(
                    msg,
                    max_message_chars=message_limit,
                )
                or changed
            )

        before_total = sum(self._approx_message_chars(msg) for msg in messages)
        if before_total <= total_limit:
            return changed

        start = max(0, len(messages) - keep_recent)
        keep_indices = set(range(start, len(messages)))
        keep_indices.update(
            idx for idx, msg in enumerate(messages) if msg.role == "system"
        )
        trimmed = [messages[idx] for idx in sorted(keep_indices)]

        while (
            sum(self._approx_message_chars(msg) for msg in trimmed) > total_limit
            and len(trimmed) > 3
        ):
            drop_idx = next(
                (idx for idx, msg in enumerate(trimmed) if msg.role != "system"),
                None,
            )
            if drop_idx is None:
                break
            trimmed.pop(drop_idx)

        self.run_context.messages = trimmed
        after_total = sum(self._approx_message_chars(msg) for msg in trimmed)
        if len(trimmed) != len(messages) or after_total != before_total:
            changed = True
            logger.warning(
                "Applied hard context guard: messages %s -> %s, approx chars %s -> %s",
                len(messages),
                len(trimmed),
                before_total,
                after_total,
            )

        return changed

    def _force_reduce_context_after_overflow(self) -> bool:
        return self._apply_hard_context_size_guard(
            max_total_chars=120000,
            max_message_chars=5000,
            keep_recent_messages=10,
        )

    def _using_skills_like_mode(self) -> bool:
        return self.tool_schema_mode == "skills_like" or self._runtime_force_skills_like

    def _estimate_tool_schema_chars(self, tool_set: ToolSet | None) -> int:
        if not isinstance(tool_set, ToolSet):
            return 0

        try:
            schema = tool_set.openai_schema()
            return len(json.dumps(schema, ensure_ascii=False))
        except Exception:
            return len(str(tool_set))

    def _build_compact_selector_tool_set(
        self,
        raw_tool_set: ToolSet,
        *,
        max_desc_chars: int,
    ) -> ToolSet:
        compact = ToolSet()
        desc_limit = max(0, min(int(max_desc_chars), 600))

        for tool in raw_tool_set:
            if hasattr(tool, "active") and not tool.active:
                continue

            description = str(getattr(tool, "description", "") or "").strip()
            if desc_limit <= 0:
                description = ""
            elif len(description) > desc_limit:
                keep = max(40, desc_limit - 16)
                description = f"{description[:keep]} ..."

            compact.add_tool(
                FunctionTool(
                    name=tool.name,
                    description=description,
                    parameters={"type": "object", "properties": {}},
                    handler=None,
                )
            )

        return compact

    async def _maybe_compact_tool_schema_in_payload(
        self,
        payload: dict[str, T.Any],
        *,
        force: bool,
        reason: str,
    ) -> bool:
        if self._using_skills_like_mode():
            if payload.get("func_tool") is not None:
                payload["func_tool"] = self.req.func_tool
            return False

        tool_set = payload.get("func_tool")
        if not isinstance(tool_set, ToolSet) or tool_set.empty():
            return False

        resilience_cfg = self._get_runtime_resilience_cfg()
        if not force and not bool(resilience_cfg.get("auto_compact_tool_schema", True)):
            return False

        schema_chars = self._estimate_tool_schema_chars(tool_set)
        threshold = self._cfg_int(
            resilience_cfg,
            "tool_schema_compact_threshold_chars",
            90000,
        )
        threshold = max(2000, min(threshold, 2_000_000))
        if not force and schema_chars <= threshold:
            return False

        desc_chars = self._cfg_int(
            resilience_cfg,
            "compact_tool_description_chars",
            160,
        )
        compact_set = self._build_compact_selector_tool_set(
            tool_set,
            max_desc_chars=desc_chars,
        )

        self._skill_like_raw_tool_set = tool_set
        self._tool_schema_param_set = tool_set.get_param_only_tool_set()
        self.req.func_tool = compact_set
        self._runtime_force_skills_like = True
        payload["func_tool"] = compact_set

        compact_schema_chars = self._estimate_tool_schema_chars(compact_set)
        logger.warning(
            "Enabled runtime compact tool schema (%s): approx chars %s -> %s",
            reason,
            schema_chars,
            compact_schema_chars,
        )
        await self._record_resilience_event(
            "llm_retry",
            (
                "enabled runtime compact tool schema "
                f"({reason}), chars {schema_chars} -> {compact_schema_chars}"
            ),
        )
        return True

    def _estimate_extra_user_content_parts_chars(
        self,
        parts: list[T.Any] | None,
    ) -> int:
        if not parts:
            return 0

        total = 0
        for part in parts:
            try:
                if hasattr(part, "model_dump"):
                    total += len(json.dumps(part.model_dump(), ensure_ascii=False))
                elif isinstance(part, dict):
                    total += len(json.dumps(part, ensure_ascii=False))
                else:
                    total += len(str(part))
            except Exception:
                total += len(str(part))
        return total

    def _estimate_payload_chars(self, payload: dict[str, T.Any]) -> int:
        contexts = payload.get("contexts") or []
        total = 0
        for msg in contexts:
            if isinstance(msg, Message):
                total += self._approx_message_chars(msg)
            elif isinstance(msg, dict):
                total += len(json.dumps(msg, ensure_ascii=False))
            else:
                total += len(str(msg))

        total += self._estimate_tool_schema_chars(payload.get("func_tool"))
        total += self._estimate_extra_user_content_parts_chars(
            payload.get("extra_user_content_parts")
        )
        return total

    async def _apply_payload_size_guard(self, payload: dict[str, T.Any]) -> bool:
        resilience_cfg = self._get_runtime_resilience_cfg()
        total_limit = self._cfg_int(
            resilience_cfg,
            "max_total_payload_chars",
            360000,
        )
        total_limit = max(30000, min(total_limit, 3_000_000))

        changed = False
        total_chars = self._estimate_payload_chars(payload)

        if total_chars <= total_limit:
            if await self._maybe_compact_tool_schema_in_payload(
                payload,
                force=False,
                reason="tool schema threshold",
            ):
                changed = True
            return changed

        if self._apply_hard_context_size_guard(
            max_total_chars=max(20000, int(total_limit * 0.55)),
            max_message_chars=min(
                self._cfg_int(resilience_cfg, "max_message_chars", 12000),
                8000,
            ),
            keep_recent_messages=min(
                self._cfg_int(resilience_cfg, "hard_keep_recent_messages", 14),
                10,
            ),
        ):
            payload["contexts"] = self.run_context.messages
            changed = True

        if await self._maybe_compact_tool_schema_in_payload(
            payload,
            force=True,
            reason="payload budget overflow",
        ):
            changed = True

        total_chars = self._estimate_payload_chars(payload)

        if (
            bool(resilience_cfg.get("drop_extra_user_content_parts_on_overflow", True))
            and payload.get("extra_user_content_parts")
            and total_chars > total_limit
        ):
            payload["extra_user_content_parts"] = []
            changed = True
            total_chars = self._estimate_payload_chars(payload)

        if (
            bool(resilience_cfg.get("overflow_disable_tools_last_resort", True))
            and payload.get("func_tool") is not None
            and total_chars > total_limit
        ):
            payload["func_tool"] = None
            changed = True
            await self._record_resilience_event(
                "llm_retry",
                (
                    "payload budget exceeded; temporarily disabled tools "
                    f"(approx chars {total_chars} > {total_limit})"
                ),
            )
            total_chars = self._estimate_payload_chars(payload)

        if changed:
            logger.warning(
                "Applied payload guard: approx chars -> %s (limit=%s)",
                total_chars,
                total_limit,
            )

        return changed

    def _build_stream_recovery_prompt(self, partial_text: str) -> str:
        tail = partial_text[-800:]
        return (
            "The previous response was interrupted because of temporary API/network instability. "
            "Continue from the interruption point without repeating existing content. "
            "Keep the same language and format.\n\n"
            f"Existing partial response tail:\n{tail}"
        )

    def _resilience_session_id(self) -> str:
        if self.req and getattr(self.req, "session_id", None):
            return str(self.req.session_id)

        astr_context = getattr(self.run_context, "context", None)
        event = getattr(astr_context, "event", None)
        if event is not None and getattr(event, "unified_msg_origin", None):
            return str(event.unified_msg_origin)
        return ""

    async def _record_resilience_event(self, event: str, detail: str) -> None:
        try:
            await coding_resilience_monitor.record_event(
                event=event,
                detail=detail,
                session_id=self._resilience_session_id(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to record resilience event %s: %s", event, exc)

    async def _maybe_auto_apply_tool_policy(self, tool_name: str) -> None:
        evo_cfg = self._get_tool_evolution_cfg()
        if not evo_cfg.get("enable", True) or not evo_cfg.get("auto_apply", False):
            return

        try:
            result = await tool_evolution_manager.maybe_auto_apply(
                tool_name=tool_name,
                min_samples=int(evo_cfg.get("min_samples", 12) or 12),
                dry_run=bool(evo_cfg.get("dry_run_default", True)),
                every_n_calls=int(evo_cfg.get("auto_apply_every_calls", 10) or 10),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tool evolution auto-apply failed for %s: %s", tool_name, exc)
            return

        if not result:
            return

        if result.get("ok") and not result.get("dry_run", True):
            logger.info(
                "Tool %s auto policy action: %s",
                tool_name,
                result.get("action", "applied"),
            )
        elif not result.get("ok"):
            logger.debug(
                "Tool %s auto policy skipped: %s",
                tool_name,
                result.get("reason", "unknown"),
            )

    async def _iter_llm_responses(
        self, *, include_model: bool = True
    ) -> T.AsyncGenerator[LLMResponse, None]:
        """Yields chunks and a final LLMResponse with resilient retries."""
        self._apply_hard_context_size_guard()
        payload = {
            "contexts": self.run_context.messages,  # list[Message]
            "func_tool": self.req.func_tool,
            "session_id": self.req.session_id,
            "extra_user_content_parts": self.req.extra_user_content_parts,  # list[ContentPart]
        }
        if include_model:
            # For primary provider we keep explicit model selection if provided.
            payload["model"] = self.req.model
        await self._apply_payload_size_guard(payload)

        resilience_cfg = self._get_runtime_resilience_cfg()
        enabled = bool(resilience_cfg.get("enable", True))
        max_retries = (
            int(resilience_cfg.get("llm_max_retries", 2) or 2) if enabled else 0
        )
        base_backoff = (
            float(resilience_cfg.get("llm_base_backoff_seconds", 1.5) or 1.5)
            if enabled
            else 0.0
        )
        max_backoff = (
            float(resilience_cfg.get("llm_max_backoff_seconds", 12.0) or 12.0)
            if enabled
            else 0.0
        )
        stream_fallback = bool(
            resilience_cfg.get("stream_fallback_to_non_stream", True)
        )
        overflow_max_retries = max(
            1,
            self._cfg_int(resilience_cfg, "overflow_max_retries", 4),
        )

        attempt = 0
        overflow_retry_count = 0
        while True:
            attempt += 1
            await self._apply_payload_size_guard(payload)
            partial_chunks: list[str] = []
            try:
                if self.streaming:
                    stream = self.provider.text_chat_stream(**payload)
                    got_final = False
                    async for resp in stream:  # type: ignore
                        if resp.is_chunk:
                            if resp.completion_text:
                                partial_chunks.append(resp.completion_text)
                            yield resp
                            continue

                        got_final = True
                        if resp.role == "err" and self._is_transient_provider_error(
                            resp.completion_text or ""
                        ):
                            raise RuntimeError(
                                resp.completion_text
                                or "Transient provider error in final stream response."
                            )
                        if attempt > 1:
                            await self._record_resilience_event(
                                "recovered",
                                f"streaming request recovered on attempt {attempt}",
                            )
                        yield resp
                        return

                    if got_final:
                        return
                    raise RuntimeError("LLM stream ended without final response.")

                resp = await self.provider.text_chat(**payload)
                if resp.role == "err" and self._is_transient_provider_error(
                    resp.completion_text or ""
                ):
                    raise RuntimeError(
                        resp.completion_text or "Transient provider error response."
                    )
                if attempt > 1:
                    await self._record_resilience_event(
                        "recovered",
                        f"request recovered on attempt {attempt}",
                    )
                yield resp
                return

            except Exception as exc:  # noqa: BLE001
                if self._is_context_overflow_error(exc):
                    overflow_retry_count += 1
                    actions: list[str] = []

                    reduced = self._force_reduce_context_after_overflow()
                    if reduced:
                        payload["contexts"] = self.run_context.messages
                        actions.append("trim_context")
                    elif overflow_retry_count == 1:
                        actions.append("retry_once")

                    if await self._maybe_compact_tool_schema_in_payload(
                        payload,
                        force=True,
                        reason=f"context overflow attempt {attempt}",
                    ):
                        actions.append("compact_tool_schema")

                    if bool(
                        resilience_cfg.get(
                            "drop_extra_user_content_parts_on_overflow",
                            True,
                        )
                    ) and payload.get("extra_user_content_parts"):
                        payload["extra_user_content_parts"] = []
                        actions.append("drop_extra_parts")

                    if (
                        overflow_retry_count >= overflow_max_retries - 1
                        and bool(
                            resilience_cfg.get(
                                "overflow_disable_tools_last_resort",
                                True,
                            )
                        )
                        and payload.get("func_tool") is not None
                    ):
                        payload["func_tool"] = None
                        actions.append("disable_tools")

                    if actions and overflow_retry_count <= overflow_max_retries:
                        action = ",".join(actions)
                        await self._record_resilience_event(
                            "llm_retry",
                            (
                                "context overflow retry "
                                f"[{action}] attempt {attempt}: {exc}"
                            ),
                        )
                        logger.warning(
                            "LLM context overflow detected; actions=%s, attempt=%s: %s",
                            action,
                            attempt,
                            exc,
                        )
                        continue

                transient = self._is_transient_provider_error(exc)

                if (
                    self.streaming
                    and stream_fallback
                    and partial_chunks
                    and transient
                    and attempt <= max_retries + 1
                ):
                    try:
                        partial_text = "".join(partial_chunks)
                        fallback_payload = dict(payload)
                        fallback_payload["contexts"] = [
                            *self.run_context.messages,
                            Message(role="assistant", content=partial_text),
                            Message(
                                role="user",
                                content=self._build_stream_recovery_prompt(
                                    partial_text
                                ),
                            ),
                        ]
                        fallback_resp = await self.provider.text_chat(
                            **fallback_payload
                        )
                        if (
                            fallback_resp.role == "err"
                            and self._is_transient_provider_error(
                                fallback_resp.completion_text or ""
                            )
                        ):
                            raise RuntimeError(
                                fallback_resp.completion_text
                                or "Transient provider fallback error."
                            )
                        await self._record_resilience_event(
                            "stream_fallback",
                            "stream interrupted and recovered by non-stream continuation",
                        )
                        await self._record_resilience_event(
                            "recovered",
                            f"stream fallback recovered on attempt {attempt}",
                        )
                        yield fallback_resp
                        return
                    except Exception as fallback_exc:  # noqa: BLE001
                        exc = fallback_exc
                        transient = self._is_transient_provider_error(fallback_exc)

                if not transient or attempt > max_retries + 1:
                    await self._record_resilience_event(
                        "failed",
                        f"llm request failed at attempt {attempt}: {exc}",
                    )
                    raise

                await self._record_resilience_event(
                    "llm_retry",
                    f"llm transient failure attempt {attempt}/{max_retries + 1}: {exc}",
                )
                backoff = min(max_backoff, base_backoff * (2 ** (attempt - 1)))
                logger.warning(
                    "LLM request transient failure (attempt %s/%s): %s",
                    attempt,
                    max_retries + 1,
                    exc,
                )
                await asyncio.sleep(backoff)

    async def _iter_llm_responses_with_fallback(
        self,
    ) -> T.AsyncGenerator[LLMResponse, None]:
        """Wrap _iter_llm_responses with provider fallback handling."""
        candidates = [self.provider, *self.fallback_providers]
        total_candidates = len(candidates)
        last_exception: Exception | None = None
        last_err_response: LLMResponse | None = None

        for idx, candidate in enumerate(candidates):
            candidate_id = candidate.provider_config.get("id", "<unknown>")
            is_last_candidate = idx == total_candidates - 1
            if idx > 0:
                logger.warning(
                    "Switched from %s to fallback chat provider: %s",
                    self.provider.provider_config.get("id", "<unknown>"),
                    candidate_id,
                )
            self.provider = candidate
            has_stream_output = False
            try:
                async for resp in self._iter_llm_responses(include_model=idx == 0):
                    if resp.is_chunk:
                        has_stream_output = True
                        yield resp
                        continue

                    if (
                        resp.role == "err"
                        and not has_stream_output
                        and (not is_last_candidate)
                    ):
                        last_err_response = resp
                        logger.warning(
                            "Chat Model %s returns error response, trying fallback to next provider.",
                            candidate_id,
                        )
                        break

                    yield resp
                    return

                if has_stream_output:
                    return
            except Exception as exc:  # noqa: BLE001
                last_exception = exc
                logger.warning(
                    "Chat Model %s request error: %s",
                    candidate_id,
                    exc,
                    exc_info=True,
                )
                continue

        if last_err_response:
            yield last_err_response
            return
        if last_exception:
            yield LLMResponse(
                role="err",
                completion_text=(
                    "All chat models failed: "
                    f"{type(last_exception).__name__}: {last_exception}"
                ),
            )
            return
        yield LLMResponse(
            role="err",
            completion_text="All available chat models are unavailable.",
        )

    def _simple_print_message_role(self, tag: str = ""):
        roles = []
        for message in self.run_context.messages:
            roles.append(message.role)
        logger.debug(f"{tag} RunCtx.messages -> [{len(roles)}] {','.join(roles)}")

    @override
    async def step(self):
        """Process a single step of the agent.
        This method should return the result of the step.
        """
        if not self.req:
            raise ValueError("Request is not set. Please call reset() first.")

        if self._state == AgentState.IDLE:
            try:
                await self.agent_hooks.on_agent_begin(self.run_context)
            except Exception as e:
                logger.error(f"Error in on_agent_begin hook: {e}", exc_info=True)

        # 开始处理，转换到运行状态
        self._transition_state(AgentState.RUNNING)
        llm_resp_result = None

        # do truncate and compress
        token_usage = self.req.conversation.token_usage if self.req.conversation else 0
        self._simple_print_message_role("[BefCompact]")
        self.run_context.messages = await self.context_manager.process(
            self.run_context.messages, trusted_token_usage=token_usage
        )
        self._simple_print_message_role("[AftCompact]")
        self._apply_hard_context_size_guard()

        async for llm_response in self._iter_llm_responses_with_fallback():
            if llm_response.is_chunk:
                # update ttft
                if self.stats.time_to_first_token == 0:
                    self.stats.time_to_first_token = time.time() - self.stats.start_time

                if llm_response.result_chain:
                    yield AgentResponse(
                        type="streaming_delta",
                        data=AgentResponseData(chain=llm_response.result_chain),
                    )
                elif llm_response.completion_text:
                    yield AgentResponse(
                        type="streaming_delta",
                        data=AgentResponseData(
                            chain=MessageChain().message(llm_response.completion_text),
                        ),
                    )
                elif llm_response.reasoning_content:
                    yield AgentResponse(
                        type="streaming_delta",
                        data=AgentResponseData(
                            chain=MessageChain(type="reasoning").message(
                                llm_response.reasoning_content,
                            ),
                        ),
                    )
                continue
            llm_resp_result = llm_response

            if not llm_response.is_chunk and llm_response.usage:
                # only count the token usage of the final response for computation purpose
                self.stats.token_usage += llm_response.usage
                if self.req.conversation:
                    self.req.conversation.token_usage = llm_response.usage.total
            break  # got final response

        if not llm_resp_result:
            return

        # 处理 LLM 响应
        llm_resp = llm_resp_result

        if llm_resp.role == "err":
            # 如果 LLM 响应错误，转换到错误状态
            self.final_llm_resp = llm_resp
            self.stats.end_time = time.time()
            self._transition_state(AgentState.ERROR)
            yield AgentResponse(
                type="err",
                data=AgentResponseData(
                    chain=MessageChain().message(
                        f"LLM 响应错误: {llm_resp.completion_text or '未知错误'}",
                    ),
                ),
            )
            return

        if not llm_resp.tools_call_name:
            llm_resp = await self._maybe_post_think_recall(llm_resp)
            # 如果没有工具调用，转换到完成状态
            self.final_llm_resp = llm_resp
            self._transition_state(AgentState.DONE)
            self.stats.end_time = time.time()

            # record the final assistant message
            parts = []
            if llm_resp.reasoning_content or llm_resp.reasoning_signature:
                parts.append(
                    ThinkPart(
                        think=llm_resp.reasoning_content,
                        encrypted=llm_resp.reasoning_signature,
                    )
                )
            if llm_resp.completion_text:
                parts.append(TextPart(text=llm_resp.completion_text))
            if len(parts) == 0:
                logger.warning(
                    "LLM returned empty assistant message with no tool calls."
                )
            self.run_context.messages.append(Message(role="assistant", content=parts))

            # call the on_agent_done hook
            try:
                await self.agent_hooks.on_agent_done(self.run_context, llm_resp)
            except Exception as e:
                logger.error(f"Error in on_agent_done hook: {e}", exc_info=True)

        # 返回 LLM 结果
        if llm_resp.result_chain:
            yield AgentResponse(
                type="llm_result",
                data=AgentResponseData(chain=llm_resp.result_chain),
            )
        elif llm_resp.completion_text:
            yield AgentResponse(
                type="llm_result",
                data=AgentResponseData(
                    chain=MessageChain().message(llm_resp.completion_text),
                ),
            )

        # 如果有工具调用，还需处理工具调用
        if llm_resp.tools_call_name:
            if self._using_skills_like_mode():
                llm_resp, _ = await self._resolve_tool_exec(llm_resp)

            tool_call_result_blocks = []
            cached_images = []  # Collect cached images for LLM visibility
            async for result in self._handle_function_tools(self.req, llm_resp):
                if result.kind == "tool_call_result_blocks":
                    if result.tool_call_result_blocks is not None:
                        tool_call_result_blocks = result.tool_call_result_blocks
                elif result.kind == "cached_image":
                    if result.cached_image is not None:
                        # Collect cached image info
                        cached_images.append(result.cached_image)
                elif result.kind == "message_chain":
                    chain = result.message_chain
                    if chain is None or chain.type is None:
                        # should not happen
                        continue
                    if chain.type == "tool_direct_result":
                        ar_type = "tool_call_result"
                    else:
                        ar_type = chain.type
                    yield AgentResponse(
                        type=ar_type,
                        data=AgentResponseData(chain=chain),
                    )

            # 将结果添加到上下文中
            parts = []
            if llm_resp.reasoning_content or llm_resp.reasoning_signature:
                parts.append(
                    ThinkPart(
                        think=llm_resp.reasoning_content,
                        encrypted=llm_resp.reasoning_signature,
                    )
                )
            if llm_resp.completion_text:
                parts.append(TextPart(text=llm_resp.completion_text))
            if len(parts) == 0:
                parts = None
            tool_calls_result = ToolCallsResult(
                tool_calls_info=AssistantMessageSegment(
                    tool_calls=llm_resp.to_openai_to_calls_model(),
                    content=parts,
                ),
                tool_calls_result=tool_call_result_blocks,
            )
            # record the assistant message with tool calls
            self.run_context.messages.extend(
                tool_calls_result.to_openai_messages_model()
            )

            # If there are cached images and the model supports image input,
            # append a user message with images so LLM can see them
            if cached_images:
                modalities = self.provider.provider_config.get("modalities", [])
                supports_image = "image" in modalities
                if supports_image:
                    # Build user message with images for LLM to review
                    image_parts = []
                    for cached_img in cached_images:
                        img_data = tool_image_cache.get_image_base64_by_path(
                            cached_img.file_path, cached_img.mime_type
                        )
                        if img_data:
                            base64_data, mime_type = img_data
                            image_parts.append(
                                TextPart(
                                    text=f"[Image from tool '{cached_img.tool_name}', path='{cached_img.file_path}']"
                                )
                            )
                            image_parts.append(
                                ImageURLPart(
                                    image_url=ImageURLPart.ImageURL(
                                        url=f"data:{mime_type};base64,{base64_data}",
                                        id=cached_img.file_path,
                                    )
                                )
                            )
                    if image_parts:
                        self.run_context.messages.append(
                            Message(role="user", content=image_parts)
                        )
                        logger.debug(
                            f"Appended {len(cached_images)} cached image(s) to context for LLM review"
                        )

            self.req.append_tool_calls_result(tool_calls_result)

    async def step_until_done(
        self, max_step: int
    ) -> T.AsyncGenerator[AgentResponse, None]:
        """Process steps until the agent is done."""
        step_count = 0
        step_retry_count = 0
        resilience_cfg = self._get_runtime_resilience_cfg()
        retry_enabled = bool(resilience_cfg.get("enable", True))
        step_max_retries = int(resilience_cfg.get("step_max_retries", 2) or 2)
        base_backoff = float(resilience_cfg.get("llm_base_backoff_seconds", 1.5) or 1.5)
        max_backoff = float(resilience_cfg.get("llm_max_backoff_seconds", 12.0) or 12.0)

        while not self.done() and step_count < max_step:
            step_count += 1
            try:
                async for resp in self.step():
                    yield resp
                if step_retry_count > 0:
                    await self._record_resilience_event(
                        "recovered",
                        f"step recovered after {step_retry_count} retries",
                    )
                step_retry_count = 0
            except Exception as exc:  # noqa: BLE001
                if (
                    retry_enabled
                    and self._is_transient_provider_error(exc)
                    and step_retry_count < step_max_retries
                ):
                    step_retry_count += 1
                    delay = min(
                        max_backoff, base_backoff * (2 ** (step_retry_count - 1))
                    )
                    await self._record_resilience_event(
                        "step_retry",
                        (
                            "transient step failure auto-resume "
                            f"{step_retry_count}/{step_max_retries}: {exc}"
                        ),
                    )
                    logger.warning(
                        "Transient step failure, auto resume attempt %s/%s after %.2fs: %s",
                        step_retry_count,
                        step_max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    step_count -= 1
                    continue

                if retry_enabled and self._is_transient_provider_error(exc):
                    await self._record_resilience_event(
                        "failed",
                        f"step failed after retries: {exc}",
                    )
                raise

        #  如果循环结束了但是 agent 还没有完成，说明是达到了 max_step
        if not self.done():
            logger.warning(
                f"Agent reached max steps ({max_step}), forcing a final response."
            )
            # 拔掉所有工具
            if self.req:
                self.req.func_tool = None
            # 注入提示词
            self.run_context.messages.append(
                Message(
                    role="user",
                    content="工具调用次数已达到上限，请停止使用工具，并根据已经收集到的信息，对你的任务和发现进行总结，然后直接回复用户。",
                )
            )
            # 再执行最后一步
            async for resp in self.step():
                yield resp

    async def _handle_function_tools(
        self,
        req: ProviderRequest,
        llm_response: LLMResponse,
    ) -> T.AsyncGenerator[_HandleFunctionToolsResult, None]:
        """处理函数工具调用。"""
        tool_call_result_blocks: list[ToolCallMessageSegment] = []
        logger.info(f"Agent 使用工具: {llm_response.tools_call_name}")

        # 执行函数调用
        for func_tool_name, func_tool_args, func_tool_id in zip(
            llm_response.tools_call_name,
            llm_response.tools_call_args,
            llm_response.tools_call_ids,
        ):
            yield _HandleFunctionToolsResult.from_message_chain(
                MessageChain(
                    type="tool_call",
                    chain=[
                        Json(
                            data={
                                "id": func_tool_id,
                                "name": func_tool_name,
                                "args": func_tool_args,
                                "ts": time.time(),
                            }
                        )
                    ],
                )
            )
            try:
                if not req.func_tool:
                    return

                if self._using_skills_like_mode() and self._skill_like_raw_tool_set:
                    # in 'skills_like' mode, raw.func_tool is light schema, does not have handler
                    # so we need to get the tool from the raw tool set
                    func_tool = self._skill_like_raw_tool_set.get_tool(func_tool_name)
                else:
                    func_tool = req.func_tool.get_tool(func_tool_name)

                logger.info(f"使用工具：{func_tool_name}，参数：{func_tool_args}")

                if not func_tool:
                    logger.warning(f"未找到指定的工具: {func_tool_name}，将跳过。")
                    await tool_evolution_manager.record_tool_call(
                        tool_name=func_tool_name,
                        success=False,
                        args=func_tool_args,
                        error=f"error: Tool {func_tool_name} not found.",
                        duration_s=0.0,
                        policy_applied={},
                    )
                    await self._maybe_auto_apply_tool_policy(func_tool_name)
                    tool_call_result_blocks.append(
                        ToolCallMessageSegment(
                            role="tool",
                            tool_call_id=func_tool_id,
                            content=f"error: Tool {func_tool_name} not found.",
                        ),
                    )
                    continue

                valid_params = {}  # 参数过滤：只传递函数实际需要的参数
                expected_param_names: list[str] | None = None

                # 获取实际的 handler 函数
                if func_tool.handler:
                    logger.debug(
                        f"工具 {func_tool_name} 期望的参数: {func_tool.parameters}",
                    )
                    if func_tool.parameters and func_tool.parameters.get("properties"):
                        expected_params = set(func_tool.parameters["properties"].keys())
                        expected_param_names = list(expected_params)

                        valid_params = {
                            k: v
                            for k, v in func_tool_args.items()
                            if k in expected_params
                        }

                    # 记录被忽略的参数
                    ignored_params = set(func_tool_args.keys()) - set(
                        valid_params.keys(),
                    )
                    if ignored_params:
                        logger.warning(
                            f"工具 {func_tool_name} 忽略非期望参数: {ignored_params}",
                        )
                else:
                    # 如果没有 handler（如 MCP 工具），使用所有参数
                    valid_params = func_tool_args

                adapt = await tool_evolution_manager.adapt_tool_call(
                    tool_name=func_tool_name,
                    args=valid_params,
                    default_timeout=self.run_context.tool_call_timeout,
                    expected_params=expected_param_names,
                )
                valid_params = adapt.get("args", valid_params)
                tool_call_timeout_override = int(
                    adapt.get("tool_call_timeout", self.run_context.tool_call_timeout)
                )
                applied_policy = adapt.get("applied", {})

                if applied_policy:
                    logger.info(
                        "Tool %s applied evolution policy: %s",
                        func_tool_name,
                        applied_policy,
                    )

                try:
                    await self.agent_hooks.on_tool_start(
                        self.run_context,
                        func_tool,
                        valid_params,
                    )
                except Exception as e:
                    logger.error(f"Error in on_tool_start hook: {e}", exc_info=True)

                executor = self.tool_executor.execute(
                    tool=func_tool,
                    run_context=self.run_context,
                    tool_call_timeout_override=tool_call_timeout_override,
                    **valid_params,  # 只传递有效的参数
                )

                _final_resp: CallToolResult | None = None
                _tool_exec_start = time.time()
                _tool_error = ""
                _tool_success = False
                async for resp in executor:  # type: ignore
                    if isinstance(resp, CallToolResult):
                        res = resp
                        _final_resp = resp
                        _tool_success = True
                        if isinstance(res.content[0], TextContent):
                            text_content = self._sanitize_tool_result_for_context(
                                res.content[0].text,
                            )
                            if text_content.strip().lower().startswith("error:"):
                                _tool_success = False
                                _tool_error = text_content[:300]
                            tool_call_result_blocks.append(
                                ToolCallMessageSegment(
                                    role="tool",
                                    tool_call_id=func_tool_id,
                                    content=text_content,
                                ),
                            )
                        elif isinstance(res.content[0], ImageContent):
                            # Cache the image instead of sending directly
                            cached_img = tool_image_cache.save_image(
                                base64_data=res.content[0].data,
                                tool_call_id=func_tool_id,
                                tool_name=func_tool_name,
                                index=0,
                                mime_type=res.content[0].mimeType or "image/png",
                            )
                            tool_call_result_blocks.append(
                                ToolCallMessageSegment(
                                    role="tool",
                                    tool_call_id=func_tool_id,
                                    content=(
                                        f"Image returned and cached at path='{cached_img.file_path}'. "
                                        f"Review the image below. Use send_message_to_user to send it to the user if satisfied, "
                                        f"with type='image' and path='{cached_img.file_path}'."
                                    ),
                                ),
                            )
                            # Yield image info for LLM visibility (will be handled in step())
                            yield _HandleFunctionToolsResult.from_cached_image(
                                cached_img
                            )
                        elif isinstance(res.content[0], EmbeddedResource):
                            resource = res.content[0].resource
                            if isinstance(resource, TextResourceContents):
                                tool_call_result_blocks.append(
                                    ToolCallMessageSegment(
                                        role="tool",
                                        tool_call_id=func_tool_id,
                                        content=self._sanitize_tool_result_for_context(
                                            resource.text,
                                        ),
                                    ),
                                )
                            elif (
                                isinstance(resource, BlobResourceContents)
                                and resource.mimeType
                                and resource.mimeType.startswith("image/")
                            ):
                                # Cache the image instead of sending directly
                                cached_img = tool_image_cache.save_image(
                                    base64_data=resource.blob,
                                    tool_call_id=func_tool_id,
                                    tool_name=func_tool_name,
                                    index=0,
                                    mime_type=resource.mimeType,
                                )
                                tool_call_result_blocks.append(
                                    ToolCallMessageSegment(
                                        role="tool",
                                        tool_call_id=func_tool_id,
                                        content=(
                                            f"Image returned and cached at path='{cached_img.file_path}'. "
                                            f"Review the image below. Use send_message_to_user to send it to the user if satisfied, "
                                            f"with type='image' and path='{cached_img.file_path}'."
                                        ),
                                    ),
                                )
                                # Yield image info for LLM visibility
                                yield _HandleFunctionToolsResult.from_cached_image(
                                    cached_img
                                )
                            else:
                                tool_call_result_blocks.append(
                                    ToolCallMessageSegment(
                                        role="tool",
                                        tool_call_id=func_tool_id,
                                        content="The tool has returned a data type that is not supported.",
                                    ),
                                )

                    elif resp is None:
                        # Tool 直接请求发送消息给用户
                        # 这里我们将直接结束 Agent Loop
                        # 发送消息逻辑在 ToolExecutor 中处理了
                        logger.warning(
                            f"{func_tool_name} 没有返回值，或者已将结果直接发送给用户。"
                        )
                        self._transition_state(AgentState.DONE)
                        self.stats.end_time = time.time()
                        _tool_success = True
                        tool_call_result_blocks.append(
                            ToolCallMessageSegment(
                                role="tool",
                                tool_call_id=func_tool_id,
                                content="The tool has no return value, or has sent the result directly to the user.",
                            ),
                        )
                    else:
                        # 不应该出现其他类型
                        logger.warning(
                            f"Tool 返回了不支持的类型: {type(resp)}。",
                        )
                        _tool_error = f"unsupported response type: {type(resp)}"
                        tool_call_result_blocks.append(
                            ToolCallMessageSegment(
                                role="tool",
                                tool_call_id=func_tool_id,
                                content="*The tool has returned an unsupported type. Please tell the user to check the definition and implementation of this tool.*",
                            ),
                        )

                await tool_evolution_manager.record_tool_call(
                    tool_name=func_tool_name,
                    success=_tool_success,
                    args=valid_params,
                    error=_tool_error,
                    duration_s=time.time() - _tool_exec_start,
                    policy_applied=applied_policy,
                )
                await self._maybe_auto_apply_tool_policy(func_tool_name)

                try:
                    await self.agent_hooks.on_tool_end(
                        self.run_context,
                        func_tool,
                        func_tool_args,
                        _final_resp,
                    )
                except Exception as e:
                    logger.error(f"Error in on_tool_end hook: {e}", exc_info=True)
            except Exception as e:
                logger.warning(traceback.format_exc())
                await tool_evolution_manager.record_tool_call(
                    tool_name=func_tool_name,
                    success=False,
                    args=locals().get("valid_params", func_tool_args),
                    error=str(e),
                    duration_s=0.0,
                    policy_applied=locals().get("applied_policy", {}),
                )
                await self._maybe_auto_apply_tool_policy(func_tool_name)
                tool_call_result_blocks.append(
                    ToolCallMessageSegment(
                        role="tool",
                        tool_call_id=func_tool_id,
                        content=self._sanitize_tool_result_for_context(
                            f"error: {e!s}",
                            max_chars=4000,
                        ),
                    ),
                )

        # yield the last tool call result
        if tool_call_result_blocks:
            last_tcr_content = self._sanitize_tool_result_for_context(
                str(tool_call_result_blocks[-1].content),
                max_chars=1800,
            )
            yield _HandleFunctionToolsResult.from_message_chain(
                MessageChain(
                    type="tool_call_result",
                    chain=[
                        Json(
                            data={
                                "id": func_tool_id,
                                "ts": time.time(),
                                "result": last_tcr_content,
                            }
                        )
                    ],
                )
            )
            logger.info(
                "Tool `%s` Result: %s",
                func_tool_name,
                self._sanitize_tool_result_for_context(last_tcr_content, max_chars=600),
            )

        # 处理函数调用响应
        if tool_call_result_blocks:
            yield _HandleFunctionToolsResult.from_tool_call_result_blocks(
                tool_call_result_blocks
            )

    def _build_tool_requery_context(
        self, tool_names: list[str]
    ) -> list[dict[str, T.Any]]:
        """Build contexts for re-querying LLM with param-only tool schemas."""
        contexts: list[dict[str, T.Any]] = []
        for msg in self.run_context.messages:
            if hasattr(msg, "model_dump"):
                contexts.append(msg.model_dump())  # type: ignore[call-arg]
            elif isinstance(msg, dict):
                contexts.append(copy.deepcopy(msg))
        instruction = (
            "You have decided to call tool(s): "
            + ", ".join(tool_names)
            + ". Now call the tool(s) with required arguments using the tool schema, "
            "and follow the existing tool-use rules."
        )
        if contexts and contexts[0].get("role") == "system":
            content = contexts[0].get("content") or ""
            contexts[0]["content"] = f"{content}\n{instruction}"
        else:
            contexts.insert(0, {"role": "system", "content": instruction})
        return contexts

    def _build_tool_subset(self, tool_set: ToolSet, tool_names: list[str]) -> ToolSet:
        """Build a subset of tools from the given tool set based on tool names."""
        subset = ToolSet()
        for name in tool_names:
            tool = tool_set.get_tool(name)
            if tool:
                subset.add_tool(tool)
        return subset

    async def _resolve_tool_exec(
        self,
        llm_resp: LLMResponse,
    ) -> tuple[LLMResponse, ToolSet | None]:
        """Used in 'skills_like' tool schema mode to re-query LLM with param-only tool schemas."""
        tool_names = llm_resp.tools_call_name
        if not tool_names:
            return llm_resp, self.req.func_tool
        full_tool_set = self.req.func_tool
        if not isinstance(full_tool_set, ToolSet):
            return llm_resp, self.req.func_tool

        subset = self._build_tool_subset(full_tool_set, tool_names)
        if not subset.tools:
            return llm_resp, full_tool_set

        if isinstance(self._tool_schema_param_set, ToolSet):
            param_subset = self._build_tool_subset(
                self._tool_schema_param_set, tool_names
            )
            if param_subset.tools and tool_names:
                contexts = self._build_tool_requery_context(tool_names)
                requery_resp = await self.provider.text_chat(
                    contexts=contexts,
                    func_tool=param_subset,
                    model=self.req.model,
                    session_id=self.req.session_id,
                )
                if requery_resp:
                    llm_resp = requery_resp

        return llm_resp, subset

    def done(self) -> bool:
        """检查 Agent 是否已完成工作"""
        return self._state in (AgentState.DONE, AgentState.ERROR)

    def get_final_llm_resp(self) -> LLMResponse | None:
        return self.final_llm_resp

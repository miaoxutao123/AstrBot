from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import cast

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.project_context.index_manager import project_index_manager
from astrbot.core.provider.provider import EmbeddingProvider


def _resolve_embedding_provider(
    context: ContextWrapper[AstrAgentContext], provider_id: str = ""
) -> tuple[EmbeddingProvider | None, str]:
    plugin_context = context.context.context

    explicit_provider_id = provider_id.strip()
    resolved_provider_id = explicit_provider_id
    if not resolved_provider_id and hasattr(plugin_context, "get_config"):
        try:
            event = context.context.event
            if hasattr(event, "unified_msg_origin"):
                cfg = plugin_context.get_config(umo=event.unified_msg_origin)
            else:
                cfg = plugin_context.get_config()
            if isinstance(cfg, dict):
                resolved_provider_id = str(
                    cfg.get("provider_settings", {})
                    .get("project_context", {})
                    .get("semantic_provider_id", "")
                    or ""
                ).strip()
        except Exception:
            resolved_provider_id = ""

    if resolved_provider_id:
        provider = plugin_context.get_provider_by_id(resolved_provider_id)
        if isinstance(provider, EmbeddingProvider):
            return provider, ""
        if explicit_provider_id:
            return (
                None,
                f"Embedding provider not found or invalid: {resolved_provider_id}",
            )

    providers = plugin_context.get_all_embedding_providers()
    if providers:
        provider = providers[0]
        if isinstance(provider, EmbeddingProvider):
            return provider, ""

    return None, "No embedding provider available. Configure one in Providers first."


@dataclass
class ProjectIndexBuildTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_project_index_build"
    description: str = (
        "Build or refresh a project-wide index (files, symbols, dependencies) for architecture-aware reasoning. "
        "Run this before symbol/dependency lookup tools if index is outdated."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "description": "Optional root directory to scan. Defaults to AstrBot root.",
                },
                "max_files": {
                    "type": "integer",
                    "description": "Maximum number of files to index.",
                    "default": 12000,
                },
                "max_file_bytes": {
                    "type": "integer",
                    "description": "Skip files larger than this size (bytes).",
                    "default": 1500000,
                },
            },
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        root: str | None = None,
        max_files: int = 12000,
        max_file_bytes: int = 1_500_000,
    ) -> ToolExecResult:
        if context.context.event.role != "admin":
            return "error: Permission denied. Project index build is only allowed for admin users."
        result = project_index_manager.build_index(
            root=root,
            max_files=max_files,
            max_file_bytes=max_file_bytes,
        )
        return json.dumps(result, ensure_ascii=False)


@dataclass
class ProjectSemanticIndexBuildTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_project_semantic_index_build"
    description: str = "Build semantic project index using an embedding provider for higher-quality architecture and code retrieval."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "string",
                    "description": "Optional embedding provider id. If omitted, use the first available embedding provider.",
                    "default": "",
                },
                "max_docs": {
                    "type": "integer",
                    "description": "Maximum number of indexed semantic documents.",
                    "default": 1800,
                },
                "max_doc_chars": {
                    "type": "integer",
                    "description": "Maximum character length per semantic document.",
                    "default": 1200,
                },
                "path_prefix": {
                    "type": "string",
                    "description": "Optional path prefix to narrow scope, e.g. dashboard/src/.",
                    "default": "",
                },
            },
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        provider_id: str = "",
        max_docs: int = 1800,
        max_doc_chars: int = 1200,
        path_prefix: str = "",
    ) -> ToolExecResult:
        if context.context.event.role != "admin":
            return "error: Permission denied. Semantic index build is only allowed for admin users."

        provider, err = _resolve_embedding_provider(context, provider_id)
        if not provider:
            return f"error: {err}"

        try:
            meta = provider.meta()
            result = await project_index_manager.build_semantic_index(
                embed_many=lambda texts: provider.get_embeddings_batch(
                    texts,
                    batch_size=16,
                    tasks_limit=2,
                    max_retries=3,
                ),
                embed_one=provider.get_embedding,
                batch_size=16,
                provider_id=meta.id,
                provider_model=meta.model or "",
                max_docs=max_docs,
                max_doc_chars=max_doc_chars,
                path_prefix=path_prefix or None,
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"error: {exc}"


@dataclass
class ProjectSemanticIndexInfoTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_project_semantic_index_info"
    description: str = "Show semantic project index metadata and provider information."
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
            return "error: Permission denied. Semantic index info is only allowed for admin users."

        try:
            data = project_index_manager.get_semantic_index_info()
            return json.dumps(data, ensure_ascii=False)
        except Exception as exc:
            return f"error: {exc}"


@dataclass
class ProjectScopeInfoTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_project_scope_info"
    description: str = "Show project-context analysis scope: supported file types, excluded paths, and current indexed path samples."
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
            return "error: Permission denied. Scope info is only allowed for admin users."

        try:
            data = project_index_manager.get_analysis_scope()
            return json.dumps(data, ensure_ascii=False)
        except Exception as exc:
            return f"error: {exc}"


@dataclass
class ProjectSemanticSearchTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_project_semantic_search"
    description: str = "Semantic search over project files using embedding vectors. Best for architecture- and intent-level retrieval."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query for project search.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of search results.",
                    "default": 8,
                },
                "path_prefix": {
                    "type": "string",
                    "description": "Optional path prefix filter, e.g. dashboard/src/.",
                    "default": "",
                },
                "provider_id": {
                    "type": "string",
                    "description": "Optional embedding provider id for query embedding.",
                    "default": "",
                },
            },
            "required": ["query"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        query: str,
        top_k: int = 8,
        path_prefix: str = "",
        provider_id: str = "",
    ) -> ToolExecResult:
        if context.context.event.role != "admin":
            return "error: Permission denied. Semantic search is only allowed for admin users."

        provider, err = _resolve_embedding_provider(context, provider_id)
        if not provider:
            return f"error: {err}"

        try:
            result = await project_index_manager.semantic_search(
                query=query,
                embed_one=cast(EmbeddingProvider, provider).get_embedding,
                top_k=top_k,
                path_prefix=path_prefix or None,
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"error: {exc}"


@dataclass
class ProjectSymbolSearchTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_project_symbol_search"
    description: str = "Search symbols from the project index. Useful for quickly locating classes/functions across the repo."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Symbol keyword to search.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum returned matches.",
                    "default": 20,
                },
                "path_prefix": {
                    "type": "string",
                    "description": "Optional path prefix filter, e.g. astrbot/core/.",
                    "default": "",
                },
                "kind": {
                    "type": "string",
                    "description": "Optional kind filter, e.g. function/class/heading_h2.",
                    "default": "",
                },
            },
            "required": ["query"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        query: str,
        limit: int = 20,
        path_prefix: str = "",
        kind: str = "",
    ) -> ToolExecResult:
        if context.context.event.role != "admin":
            return "error: Permission denied. Symbol search is only allowed for admin users."
        try:
            result = project_index_manager.search_symbols(
                query=query,
                limit=limit,
                path_prefix=path_prefix or None,
                kind=kind or None,
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"error: {exc}"


@dataclass
class ProjectDependencyTraceTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_project_dep_trace"
    description: str = "Trace file dependencies from project index. Use for inbound/outbound impact analysis before changes."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Indexed file path, e.g. astrbot/core/astr_main_agent.py",
                },
                "depth": {
                    "type": "integer",
                    "description": "Trace depth, range 1-6.",
                    "default": 2,
                },
                "direction": {
                    "type": "string",
                    "description": "outbound (what it depends on) or inbound (what depends on it).",
                    "default": "outbound",
                },
                "limit_nodes": {
                    "type": "integer",
                    "description": "Maximum nodes in traversal graph.",
                    "default": 200,
                },
            },
            "required": ["file_path"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        file_path: str,
        depth: int = 2,
        direction: str = "outbound",
        limit_nodes: int = 200,
    ) -> ToolExecResult:
        if context.context.event.role != "admin":
            return "error: Permission denied. Dependency trace is only allowed for admin users."
        try:
            result = project_index_manager.trace_dependency(
                file_path=file_path,
                depth=depth,
                direction=direction,
                limit_nodes=limit_nodes,
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"error: {exc}"


@dataclass
class ProjectArchitectureSummaryTool(FunctionTool[AstrAgentContext]):
    name: str = "astrbot_project_arch_summary"
    description: str = "Get architecture summary from project index: entry points, heavy files, dependency hot spots, language/directory distribution."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "top_n": {
                    "type": "integer",
                    "description": "Top N items for each ranking section.",
                    "default": 10,
                }
            },
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        top_n: int = 10,
    ) -> ToolExecResult:
        if context.context.event.role != "admin":
            return "error: Permission denied. Architecture summary is only allowed for admin users."
        try:
            result = project_index_manager.architecture_summary(top_n=top_n)
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"error: {exc}"


PROJECT_INDEX_BUILD_TOOL = ProjectIndexBuildTool()
PROJECT_SEMANTIC_INDEX_BUILD_TOOL = ProjectSemanticIndexBuildTool()
PROJECT_SEMANTIC_INDEX_INFO_TOOL = ProjectSemanticIndexInfoTool()
PROJECT_SCOPE_INFO_TOOL = ProjectScopeInfoTool()
PROJECT_SEMANTIC_SEARCH_TOOL = ProjectSemanticSearchTool()
PROJECT_SYMBOL_SEARCH_TOOL = ProjectSymbolSearchTool()
PROJECT_DEP_TRACE_TOOL = ProjectDependencyTraceTool()
PROJECT_ARCH_SUMMARY_TOOL = ProjectArchitectureSummaryTool()

__all__ = [
    "PROJECT_INDEX_BUILD_TOOL",
    "PROJECT_SEMANTIC_INDEX_BUILD_TOOL",
    "PROJECT_SEMANTIC_INDEX_INFO_TOOL",
    "PROJECT_SCOPE_INFO_TOOL",
    "PROJECT_SEMANTIC_SEARCH_TOOL",
    "PROJECT_SYMBOL_SEARCH_TOOL",
    "PROJECT_DEP_TRACE_TOOL",
    "PROJECT_ARCH_SUMMARY_TOOL",
    "ProjectIndexBuildTool",
    "ProjectSemanticIndexBuildTool",
    "ProjectSemanticIndexInfoTool",
    "ProjectScopeInfoTool",
    "ProjectSemanticSearchTool",
    "ProjectSymbolSearchTool",
    "ProjectDependencyTraceTool",
    "ProjectArchitectureSummaryTool",
]

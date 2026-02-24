import traceback
from typing import TYPE_CHECKING, Any

from quart import jsonify, request

from astrbot.core import logger
from astrbot.core.project_context.index_manager import project_index_manager
from astrbot.core.provider.provider import EmbeddingProvider

from .route import Response, Route, RouteContext

if TYPE_CHECKING:
    from astrbot.core.core_lifecycle import AstrBotCoreLifecycle


class ProjectContextRoute(Route):
    def __init__(
        self,
        context: RouteContext,
        core_lifecycle: "AstrBotCoreLifecycle | None" = None,
    ) -> None:
        super().__init__(context)
        self.core_lifecycle = core_lifecycle
        self.routes = [
            ("/project_context/build", ("POST", self.build_index)),
            ("/project_context/info", ("GET", self.get_info)),
            ("/project_context/scope", ("GET", self.get_scope)),
            ("/project_context/symbols", ("GET", self.search_symbols)),
            ("/project_context/dependency", ("GET", self.trace_dependency)),
            ("/project_context/summary", ("GET", self.arch_summary)),
            ("/project_context/semantic/info", ("GET", self.semantic_info)),
            ("/project_context/semantic/providers", ("GET", self.semantic_providers)),
            ("/project_context/semantic/build", ("POST", self.semantic_build)),
            ("/project_context/semantic/search", ("GET", self.semantic_search)),
        ]
        self.register_routes()

    def _coerce_int(
        self,
        value: Any,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))

    def _resolve_embedding_provider(
        self, provider_id: str
    ) -> tuple[EmbeddingProvider | None, str]:
        if not self.core_lifecycle:
            return None, "Core lifecycle not available."

        plugin_context = self.core_lifecycle.plugin_manager.context
        explicit_provider_id = provider_id.strip()
        resolved_provider_id = explicit_provider_id
        if not resolved_provider_id:
            pctx_cfg = self.config.get("provider_settings", {}).get(
                "project_context", {}
            )
            resolved_provider_id = str(
                pctx_cfg.get("semantic_provider_id", "") or ""
            ).strip()

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
        if providers and isinstance(providers[0], EmbeddingProvider):
            return providers[0], ""

        return None, "No embedding provider available. Configure one in Providers."

    def _default_index_info(self) -> dict[str, Any]:
        return {
            "schema_version": None,
            "built_at": None,
            "scan_root": "",
            "stats": {
                "scanned_files": 0,
                "indexed_files": 0,
                "skipped_large_files": 0,
                "skipped_binary_files": 0,
                "total_lines": 0,
            },
            "top_languages": [],
            "top_dirs": [],
            "entry_candidates": [],
            "needs_build": True,
        }

    def _default_arch_summary(self, top_n: int = 10) -> dict[str, Any]:
        return {
            "built_at": None,
            "scan_root": "",
            "stats": {
                "scanned_files": 0,
                "indexed_files": 0,
                "skipped_large_files": 0,
                "skipped_binary_files": 0,
                "total_lines": 0,
            },
            "top_languages": [],
            "top_dirs": [],
            "entry_candidates": [],
            "heavy_files": [],
            "hot_dependencies": [],
            "test_file_count": 0,
            "sample_test_files": [],
            "top_n": top_n,
            "needs_build": True,
        }

    def _default_semantic_info(self) -> dict[str, Any]:
        return {
            "schema_version": None,
            "built_at": None,
            "source_index_built_at": None,
            "provider_id": "",
            "provider_model": "",
            "dimension": 0,
            "stats": {
                "doc_count": 0,
                "requested_docs": 0,
                "max_docs": 0,
                "max_doc_chars": 0,
                "path_prefix": "",
                "skipped_docs": 0,
                "skip_reason_samples": [],
            },
            "needs_build": True,
        }

    def _semantic_build_error_hint(self, error: Exception | str) -> str:
        raw = str(error or "")
        lowered = raw.lower()

        if (
            "malicious" in lowered
            or "恶意" in raw
            or "<!doctype html" in lowered
            or "permissiondenied" in lowered
        ):
            return (
                "Embedding provider blocked part of the payload as suspicious. "
                "This usually comes from generated/base64 blobs in source snippets. "
                "Try narrowing path_prefix (e.g. astrbot/ or dashboard/src/) and rebuild."
            )

        return ""

    async def build_index(self):
        try:
            payload = await request.get_json(silent=True)
            payload = payload or {}
            result = project_index_manager.build_index(
                root=payload.get("root"),
                max_files=self._coerce_int(
                    payload.get("max_files", 12000),
                    default=12000,
                    minimum=1,
                    maximum=200000,
                ),
                max_file_bytes=self._coerce_int(
                    payload.get("max_file_bytes", 1500000),
                    default=1500000,
                    minimum=1024,
                    maximum=20_000_000,
                ),
            )
            return jsonify(Response().ok(data=result).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(Response().error(f"Failed to build index: {e!s}").__dict__)

    async def get_info(self):
        try:
            result = project_index_manager.get_index_info()
            return jsonify(Response().ok(data=result).__dict__)
        except FileNotFoundError:
            return jsonify(Response().ok(data=self._default_index_info()).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(
                Response().error(f"Failed to get index info: {e!s}").__dict__
            )

    async def get_scope(self):
        try:
            result = project_index_manager.get_analysis_scope()
            return jsonify(Response().ok(data=result).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(
                Response().error(f"Failed to get analysis scope: {e!s}").__dict__
            )

    async def search_symbols(self):
        try:
            query = request.args.get("query", "", type=str)
            if not query:
                return jsonify(Response().error("query is required").__dict__)
            result = project_index_manager.search_symbols(
                query=query,
                limit=request.args.get("limit", 20, type=int),
                path_prefix=request.args.get("path_prefix", "", type=str) or None,
                kind=request.args.get("kind", "", type=str) or None,
            )
            return jsonify(Response().ok(data=result).__dict__)
        except FileNotFoundError:
            return jsonify(Response().ok(data=[]).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(
                Response().error(f"Failed to search symbols: {e!s}").__dict__
            )

    async def trace_dependency(self):
        try:
            file_path = request.args.get("file_path", "", type=str)
            if not file_path:
                return jsonify(Response().error("file_path is required").__dict__)
            result = project_index_manager.trace_dependency(
                file_path=file_path,
                depth=request.args.get("depth", 2, type=int),
                direction=request.args.get("direction", "outbound", type=str),
                limit_nodes=request.args.get("limit_nodes", 200, type=int),
            )
            return jsonify(Response().ok(data=result).__dict__)
        except FileNotFoundError:
            return jsonify(
                Response()
                .error(
                    "Project index not built. Build with /api/project_context/build first."
                )
                .__dict__
            )
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(
                Response().error(f"Failed to trace dependency: {e!s}").__dict__
            )

    async def arch_summary(self):
        try:
            top_n = request.args.get("top_n", 10, type=int)
            result = project_index_manager.architecture_summary(top_n=top_n)
            return jsonify(Response().ok(data=result).__dict__)
        except FileNotFoundError:
            top_n = request.args.get("top_n", 10, type=int)
            return jsonify(
                Response().ok(data=self._default_arch_summary(top_n=top_n)).__dict__
            )
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(Response().error(f"Failed to get summary: {e!s}").__dict__)

    async def semantic_info(self):
        try:
            result = project_index_manager.get_semantic_index_info()
            return jsonify(Response().ok(data=result).__dict__)
        except FileNotFoundError:
            return jsonify(Response().ok(data=self._default_semantic_info()).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(
                Response().error(f"Failed to get semantic info: {e!s}").__dict__
            )

    async def semantic_providers(self):
        try:
            if not self.core_lifecycle:
                return jsonify(
                    Response().error("Core lifecycle not available.").__dict__
                )

            plugin_context = self.core_lifecycle.plugin_manager.context
            providers = plugin_context.get_all_embedding_providers()

            data: list[dict] = []
            for provider in providers:
                if not isinstance(provider, EmbeddingProvider):
                    continue
                meta = provider.meta()
                try:
                    dim = int(provider.get_dim())
                except Exception:
                    dim = 0
                data.append(
                    {
                        "id": meta.id,
                        "model": meta.model or "",
                        "dim": dim,
                    }
                )

            pctx_cfg = self.config.get("provider_settings", {}).get(
                "project_context", {}
            )
            configured_id = str(pctx_cfg.get("semantic_provider_id", "") or "")
            ids = {item["id"] for item in data}
            default_provider_id = (
                configured_id if configured_id and configured_id in ids else ""
            )
            if not default_provider_id and data:
                default_provider_id = data[0]["id"]

            return jsonify(
                Response()
                .ok(
                    data={
                        "providers": data,
                        "default_provider_id": default_provider_id,
                    }
                )
                .__dict__
            )
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(
                Response().error(f"Failed to get embedding providers: {e!s}").__dict__
            )

    async def semantic_build(self):
        try:
            payload = await request.get_json(silent=True)
            payload = payload or {}
            provider_id = str(payload.get("provider_id", "") or "")
            provider, err = self._resolve_embedding_provider(provider_id)
            if not provider:
                return jsonify(Response().error(err).__dict__)

            meta = provider.meta()
            batch_size = self._coerce_int(
                payload.get("batch_size", 16),
                default=16,
                minimum=1,
                maximum=64,
            )
            tasks_limit = self._coerce_int(
                payload.get("tasks_limit", 2),
                default=2,
                minimum=1,
                maximum=16,
            )
            max_retries = self._coerce_int(
                payload.get("max_retries", 3),
                default=3,
                minimum=0,
                maximum=10,
            )
            build_kwargs = {
                "embed_many": lambda texts: provider.get_embeddings_batch(
                    texts,
                    batch_size=batch_size,
                    tasks_limit=tasks_limit,
                    max_retries=max_retries,
                ),
                "embed_one": provider.get_embedding,
                "batch_size": batch_size,
                "provider_id": meta.id,
                "provider_model": meta.model or "",
                "max_docs": self._coerce_int(
                    payload.get("max_docs", 1800),
                    default=1800,
                    minimum=20,
                    maximum=5000,
                ),
                "max_doc_chars": self._coerce_int(
                    payload.get("max_doc_chars", 1200),
                    default=1200,
                    minimum=200,
                    maximum=3000,
                ),
                "path_prefix": str(payload.get("path_prefix", "") or "") or None,
            }

            try:
                result = await project_index_manager.build_semantic_index(
                    **build_kwargs
                )
            except FileNotFoundError:
                project_index_manager.build_index(
                    max_files=self._coerce_int(
                        payload.get("max_files", 12000),
                        default=12000,
                        minimum=1,
                        maximum=200000,
                    ),
                    max_file_bytes=self._coerce_int(
                        payload.get("max_file_bytes", 1500000),
                        default=1500000,
                        minimum=1024,
                        maximum=20_000_000,
                    ),
                )
                result = await project_index_manager.build_semantic_index(
                    **build_kwargs
                )

            return jsonify(Response().ok(data=result).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            hint = self._semantic_build_error_hint(e)
            suffix = f" Hint: {hint}" if hint else ""
            return jsonify(
                Response()
                .error(f"Failed to build semantic index: {e!s}{suffix}")
                .__dict__
            )

    async def semantic_search(self):
        try:
            query = request.args.get("query", "", type=str)
            if not query:
                return jsonify(Response().error("query is required").__dict__)

            provider_id = request.args.get("provider_id", "", type=str)
            provider, err = self._resolve_embedding_provider(provider_id)
            if not provider:
                return jsonify(Response().error(err).__dict__)

            result = await project_index_manager.semantic_search(
                query=query,
                embed_one=provider.get_embedding,
                top_k=request.args.get("top_k", 8, type=int),
                path_prefix=request.args.get("path_prefix", "", type=str) or None,
            )
            return jsonify(Response().ok(data=result).__dict__)
        except FileNotFoundError:
            return jsonify(Response().ok(data=[]).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(
                Response().error(f"Failed to semantic search: {e!s}").__dict__
            )

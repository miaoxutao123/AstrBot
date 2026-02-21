from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path, get_astrbot_root

INDEX_SCHEMA_VERSION = 1

_TEXT_FILE_EXTS = {
    ".py",
    ".pyi",
    ".md",
    ".txt",
    ".rst",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".ini",
    ".cfg",
    ".env",
    ".sql",
    ".sh",
    ".bat",
    ".ps1",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".go",
    ".java",
    ".kt",
    ".rs",
    ".c",
    ".h",
    ".hpp",
    ".cc",
    ".cpp",
    ".cs",
    ".html",
    ".css",
}

_DIRECT_FILE_ALLOWLIST = {
    "Dockerfile",
    "Makefile",
    "README",
    "README.md",
    "README_en.md",
    "AGENTS.md",
    "compose.yml",
    "compose.yaml",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
}

_DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".svn",
    ".hg",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".idea",
    ".vscode",
    ".DS_Store",
}

_DEFAULT_EXCLUDE_GLOBS = (
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.mp3",
    "*.wav",
    "*.mp4",
    "*.zip",
    "*.faiss",
    "*.db",
    "*.sqlite",
    "*.ttf",
    "*.otf",
)


_DATA_URL_RE = re.compile(r"data:[^\s'\"<>)]{80,}", re.IGNORECASE)
_LONG_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
_LONG_HEX_RE = re.compile(r"[0-9a-fA-F]{200,}")
_LONG_URL_RE = re.compile(r"https?://\S{180,}", re.IGNORECASE)


@dataclass(slots=True)
class BuildStats:
    scanned_files: int = 0
    indexed_files: int = 0
    skipped_large_files: int = 0
    skipped_binary_files: int = 0


class ProjectIndexManager:
    """Build and query a project-wide index for architecture-aware tooling."""

    def __init__(self, workspace_root: str | None = None) -> None:
        self.workspace_root = Path(workspace_root or get_astrbot_root()).resolve()
        self.storage_dir = Path(get_astrbot_data_path()) / "project_context"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.storage_dir / "index.json"
        self.semantic_index_file = self.storage_dir / "semantic_index.json"

    def _safe_resolve_root(self, root: str | None) -> Path:
        target = Path(root or self.workspace_root).expanduser().resolve()
        if not target.exists():
            raise FileNotFoundError(f"Path not found: {target}")
        if not target.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {target}")
        return target

    def _should_skip_file(
        self, file_path: Path, max_file_bytes: int
    ) -> tuple[bool, str]:
        if file_path.name in _DIRECT_FILE_ALLOWLIST:
            return False, ""

        suffix = file_path.suffix.lower()
        if suffix not in _TEXT_FILE_EXTS:
            return True, "binary_or_unsupported"

        for pattern in _DEFAULT_EXCLUDE_GLOBS:
            if file_path.match(pattern):
                return True, "glob_excluded"

        try:
            size = file_path.stat().st_size
        except Exception:
            return True, "stat_failed"

        if size > max_file_bytes:
            return True, "too_large"
        return False, ""

    def _to_rel(self, abs_path: Path, root: Path) -> str:
        return abs_path.resolve().relative_to(root).as_posix()

    def _read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def _sha1(self, text: str) -> str:
        return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()

    def _parse_python(self, content: str) -> tuple[list[dict], list[str], str | None]:
        symbols: list[dict] = []
        imports: list[str] = []
        module_doc: str | None = None

        try:
            tree = ast.parse(content)
        except Exception:
            return symbols, imports, module_doc

        module_doc = ast.get_docstring(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                dots = "." * node.level
                imports.append(f"{dots}{module}" if module else dots)
            elif isinstance(node, ast.ClassDef):
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "class",
                        "line": int(getattr(node, "lineno", 0) or 0),
                    }
                )
            elif isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "function",
                        "line": int(getattr(node, "lineno", 0) or 0),
                    }
                )
        return symbols, imports, module_doc

    def _parse_js_ts(self, content: str) -> tuple[list[dict], list[str]]:
        symbols: list[dict] = []
        imports: list[str] = []

        import_patterns = [
            r"import\s+.+?\s+from\s+['\"]([^'\"]+)['\"]",
            r"require\(\s*['\"]([^'\"]+)['\"]\s*\)",
            r"export\s+\*\s+from\s+['\"]([^'\"]+)['\"]",
        ]
        symbol_patterns = [
            ("class", r"class\s+([A-Za-z_][A-Za-z0-9_]*)"),
            (
                "function",
                r"(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            ),
            (
                "function",
                r"(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\(",
            ),
        ]

        for pattern in import_patterns:
            for hit in re.findall(pattern, content):
                imports.append(hit)

        for kind, pattern in symbol_patterns:
            for match in re.finditer(pattern, content):
                line = content[: match.start()].count("\n") + 1
                symbols.append({"name": match.group(1), "kind": kind, "line": line})

        return symbols, imports

    def _parse_markdown(self, content: str) -> list[dict]:
        symbols: list[dict] = []
        for line_no, line in enumerate(content.splitlines(), start=1):
            if not line.startswith("#"):
                continue
            title = line.lstrip("#").strip()
            if not title:
                continue
            level = len(line) - len(line.lstrip("#"))
            symbols.append(
                {
                    "name": title,
                    "kind": f"heading_h{level}",
                    "line": line_no,
                }
            )
        return symbols

    def _python_module_name(self, rel_path: str) -> str | None:
        if not rel_path.endswith(".py"):
            return None
        if rel_path.endswith("/__init__.py"):
            rel_path = rel_path[: -len("/__init__.py")]
        else:
            rel_path = rel_path[: -len(".py")]
        if not rel_path:
            return None
        return rel_path.replace("/", ".")

    def _resolve_local_python_import(
        self,
        import_str: str,
        current_file: str,
        module_to_file: dict[str, str],
    ) -> str | None:
        if not import_str:
            return None

        if import_str.startswith("."):
            current_module = self._python_module_name(current_file) or ""
            current_parts = current_module.split(".") if current_module else []
            if current_file.endswith("/__init__.py"):
                package_parts = current_parts
            else:
                package_parts = current_parts[:-1]

            level = len(import_str) - len(import_str.lstrip("."))
            module_part = import_str[level:]
            if level > len(package_parts):
                return None
            prefix = package_parts[: len(package_parts) - level]
            if module_part:
                prefix.extend(module_part.split("."))
            module_name = ".".join([p for p in prefix if p])
        else:
            module_name = import_str

        if module_name in module_to_file:
            return module_to_file[module_name]

        while "." in module_name:
            module_name = module_name.rsplit(".", 1)[0]
            if module_name in module_to_file:
                return module_to_file[module_name]
        return None

    def build_index(
        self,
        *,
        root: str | None = None,
        max_files: int = 12000,
        max_file_bytes: int = 1_500_000,
    ) -> dict[str, Any]:
        """Build and persist project index.

        root: directory to scan. Defaults to workspace root.
        max_files: hard cap to avoid scanning giant trees.
        max_file_bytes: skip files larger than this size.
        """

        scan_root = self._safe_resolve_root(root)
        stats = BuildStats()

        files: list[dict[str, Any]] = []
        module_to_file: dict[str, str] = {}
        line_total = 0

        for curr_root, dir_names, file_names in os.walk(scan_root):
            curr_path = Path(curr_root)
            dir_names[:] = [
                d
                for d in dir_names
                if d not in _DEFAULT_EXCLUDE_DIRS and not d.startswith(".")
            ]

            for file_name in file_names:
                if stats.indexed_files >= max_files:
                    logger.warning(
                        "Project index reached max_files=%s, stop scanning.",
                        max_files,
                    )
                    break

                stats.scanned_files += 1
                abs_file = curr_path / file_name

                skip, reason = self._should_skip_file(abs_file, max_file_bytes)
                if skip:
                    if reason == "too_large":
                        stats.skipped_large_files += 1
                    elif reason == "binary_or_unsupported":
                        stats.skipped_binary_files += 1
                    continue

                try:
                    content = self._read_text(abs_file)
                except Exception:
                    continue

                rel = self._to_rel(abs_file, scan_root)
                suffix = abs_file.suffix.lower()
                line_count = content.count("\n") + 1 if content else 0
                line_total += line_count

                symbols: list[dict] = []
                imports: list[str] = []
                doc_excerpt = ""

                if suffix in {".py", ".pyi"}:
                    symbols, imports, module_doc = self._parse_python(content)
                    if module_doc:
                        doc_excerpt = module_doc[:400]
                elif suffix in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
                    symbols, imports = self._parse_js_ts(content)
                elif suffix in {".md", ".rst"}:
                    symbols = self._parse_markdown(content)

                if not doc_excerpt:
                    doc_excerpt = "\n".join(content.splitlines()[:8])[:400]

                module_name = self._python_module_name(rel)
                if module_name:
                    module_to_file[module_name] = rel

                files.append(
                    {
                        "path": rel,
                        "ext": suffix,
                        "size": len(content.encode("utf-8", errors="replace")),
                        "line_count": line_count,
                        "hash": self._sha1(content),
                        "symbols": symbols,
                        "imports": sorted(set(imports)),
                        "local_imports": [],
                        "doc_excerpt": doc_excerpt,
                    }
                )
                stats.indexed_files += 1

            if stats.indexed_files >= max_files:
                break

        file_map = {item["path"]: item for item in files}

        graph: dict[str, list[str]] = {}
        reverse_graph: dict[str, list[str]] = defaultdict(list)

        for item in files:
            rel_path = item["path"]
            local_imports: set[str] = set()
            if item["ext"] in {".py", ".pyi"}:
                for import_str in item["imports"]:
                    target = self._resolve_local_python_import(
                        import_str,
                        rel_path,
                        module_to_file,
                    )
                    if target and target in file_map:
                        local_imports.add(target)
            item["local_imports"] = sorted(local_imports)
            graph[rel_path] = item["local_imports"]

            for target in item["local_imports"]:
                reverse_graph[target].append(rel_path)

        lang_counter: Counter[str] = Counter()
        for item in files:
            ext = item["ext"] or "(no_ext)"
            lang_counter[ext] += 1

        dir_counter: Counter[str] = Counter()
        for item in files:
            parts = Path(item["path"]).parts
            if parts:
                root_dir = parts[0]
            else:
                root_dir = "."
            dir_counter[root_dir] += 1

        entry_candidates = sorted(
            {
                item["path"]
                for item in files
                if Path(item["path"]).name
                in {
                    "main.py",
                    "app.py",
                    "manage.py",
                    "server.py",
                    "Dockerfile",
                    "compose.yml",
                    "compose.yaml",
                    "pyproject.toml",
                    "package.json",
                    "README.md",
                    "README_en.md",
                    "AGENTS.md",
                }
            }
        )

        index_payload = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "workspace_root": self.workspace_root.as_posix(),
            "scan_root": scan_root.as_posix(),
            "stats": {
                "scanned_files": stats.scanned_files,
                "indexed_files": stats.indexed_files,
                "skipped_large_files": stats.skipped_large_files,
                "skipped_binary_files": stats.skipped_binary_files,
                "total_lines": line_total,
            },
            "languages": dict(lang_counter),
            "top_dirs": dir_counter.most_common(50),
            "entry_candidates": entry_candidates,
            "files": files,
            "graph": graph,
            "reverse_graph": {k: sorted(set(v)) for k, v in reverse_graph.items()},
            "module_to_file": module_to_file,
        }

        self.index_file.write_text(
            json.dumps(index_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "scan_root": scan_root.as_posix(),
            "indexed_files": stats.indexed_files,
            "scanned_files": stats.scanned_files,
            "skipped_large_files": stats.skipped_large_files,
            "skipped_binary_files": stats.skipped_binary_files,
            "entry_candidates": entry_candidates[:12],
            "top_languages": lang_counter.most_common(12),
            "top_dirs": dir_counter.most_common(12),
        }

    def _load_index(self) -> dict[str, Any]:
        if not self.index_file.exists():
            raise FileNotFoundError(
                "Project index not found. Build index with astrbot_project_index_build first."
            )
        return json.loads(self.index_file.read_text(encoding="utf-8"))

    def get_index_info(self) -> dict[str, Any]:
        index_data = self._load_index()
        return {
            "schema_version": index_data.get("schema_version"),
            "built_at": index_data.get("built_at"),
            "scan_root": index_data.get("scan_root"),
            "stats": index_data.get("stats", {}),
            "top_languages": sorted(
                (index_data.get("languages") or {}).items(),
                key=lambda item: item[1],
                reverse=True,
            )[:12],
            "top_dirs": (index_data.get("top_dirs") or [])[:12],
            "entry_candidates": (index_data.get("entry_candidates") or [])[:12],
        }

    def search_symbols(
        self,
        *,
        query: str,
        limit: int = 20,
        path_prefix: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        index_data = self._load_index()
        files = index_data.get("files", [])

        query_norm = query.strip().lower()
        if not query_norm:
            return []

        prefix = path_prefix.strip("/") if path_prefix else ""
        results: list[dict[str, Any]] = []

        for item in files:
            file_path = item.get("path", "")
            if prefix and not file_path.startswith(prefix):
                continue

            for symbol in item.get("symbols", []):
                name = str(symbol.get("name", ""))
                symbol_kind = str(symbol.get("kind", ""))
                if kind and symbol_kind != kind:
                    continue

                name_norm = name.lower()
                if query_norm not in name_norm:
                    continue

                score = 100
                if name_norm == query_norm:
                    score += 100
                elif name_norm.startswith(query_norm):
                    score += 40
                if query_norm in file_path.lower():
                    score += 10

                results.append(
                    {
                        "score": score,
                        "name": name,
                        "kind": symbol_kind,
                        "line": symbol.get("line", 0),
                        "path": file_path,
                    }
                )

        results.sort(key=lambda item: (-int(item["score"]), item["path"], item["name"]))
        return results[: max(1, min(limit, 200))]

    def trace_dependency(
        self,
        *,
        file_path: str,
        depth: int = 2,
        direction: str = "outbound",
        limit_nodes: int = 200,
    ) -> dict[str, Any]:
        index_data = self._load_index()
        graph = index_data.get("graph", {})
        reverse_graph = index_data.get("reverse_graph", {})

        direction = direction.lower().strip()
        if direction not in {"outbound", "inbound"}:
            raise ValueError("direction must be outbound or inbound")

        max_depth = max(1, min(depth, 6))

        source = file_path.strip().strip("/")
        if source not in graph and source not in reverse_graph:
            raise ValueError(f"File not found in index: {source}")

        adjacency = graph if direction == "outbound" else reverse_graph

        nodes_seen: set[str] = {source}
        edges: list[dict[str, Any]] = []
        queue: deque[tuple[str, int]] = deque([(source, 0)])

        while queue and len(nodes_seen) < limit_nodes:
            current, curr_depth = queue.popleft()
            if curr_depth >= max_depth:
                continue
            neighbors = adjacency.get(current, [])
            for neighbor in neighbors:
                if len(nodes_seen) >= limit_nodes:
                    break
                edges.append(
                    {
                        "from": current if direction == "outbound" else neighbor,
                        "to": neighbor if direction == "outbound" else current,
                        "depth": curr_depth + 1,
                    }
                )
                if neighbor in nodes_seen:
                    continue
                nodes_seen.add(neighbor)
                queue.append((neighbor, curr_depth + 1))

        return {
            "source": source,
            "direction": direction,
            "depth": max_depth,
            "node_count": len(nodes_seen),
            "edge_count": len(edges),
            "nodes": sorted(nodes_seen),
            "edges": edges,
        }

    def architecture_summary(self, *, top_n: int = 10) -> dict[str, Any]:
        index_data = self._load_index()
        files = index_data.get("files", [])
        graph = index_data.get("graph", {})
        reverse_graph = index_data.get("reverse_graph", {})

        top_n = max(3, min(top_n, 20))

        heavy_files = sorted(
            (
                {
                    "path": item.get("path"),
                    "line_count": item.get("line_count", 0),
                    "symbol_count": len(item.get("symbols", [])),
                }
                for item in files
            ),
            key=lambda x: (x["line_count"], x["symbol_count"]),
            reverse=True,
        )[:top_n]

        hot_dependencies = sorted(
            (
                {
                    "path": path,
                    "out_degree": len(targets),
                    "in_degree": len(reverse_graph.get(path, [])),
                }
                for path, targets in graph.items()
            ),
            key=lambda x: (x["in_degree"] + x["out_degree"], x["in_degree"]),
            reverse=True,
        )[:top_n]

        test_files = [
            item["path"]
            for item in files
            if (
                item["path"].startswith("tests/")
                or "/tests/" in item["path"]
                or item["path"].endswith("_test.py")
                or item["path"].startswith("test_")
            )
        ]

        return {
            "built_at": index_data.get("built_at"),
            "scan_root": index_data.get("scan_root"),
            "stats": index_data.get("stats", {}),
            "top_languages": sorted(
                (index_data.get("languages") or {}).items(),
                key=lambda item: item[1],
                reverse=True,
            )[:top_n],
            "top_dirs": (index_data.get("top_dirs") or [])[:top_n],
            "entry_candidates": (index_data.get("entry_candidates") or [])[:top_n],
            "heavy_files": heavy_files,
            "hot_dependencies": hot_dependencies,
            "test_file_count": len(test_files),
            "sample_test_files": test_files[:top_n],
        }

    def _build_semantic_documents(
        self,
        *,
        index_data: dict[str, Any],
        max_docs: int,
        max_doc_chars: int,
        path_prefix: str | None = None,
    ) -> list[dict[str, Any]]:
        files = index_data.get("files", [])
        prefix = path_prefix.strip("/") if path_prefix else ""
        docs: list[dict[str, Any]] = []

        for item in files:
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            if prefix and not path.startswith(prefix):
                continue

            symbols = [
                str(symbol.get("name", "")).strip()
                for symbol in item.get("symbols", [])[:40]
                if str(symbol.get("name", "")).strip()
            ]
            imports = [
                str(imp).strip()
                for imp in item.get("imports", [])[:25]
                if str(imp).strip()
            ]
            excerpt_raw = str(item.get("doc_excerpt", "") or "")
            excerpt = self._sanitize_semantic_text(excerpt_raw, max_chars=520)
            line_count = int(item.get("line_count", 0) or 0)
            symbol_count = len(item.get("symbols", []))

            merged = (
                f"path: {path}\n"
                f"symbols: {', '.join(symbols[:30])}\n"
                f"imports: {', '.join(imports[:20])}\n"
                f"excerpt:\n{excerpt}"
            )
            merged = self._sanitize_semantic_text(
                merged,
                max_chars=max(80, min(max_doc_chars, 3000)),
            )
            if not merged:
                continue

            docs.append(
                {
                    "doc_id": f"file::{path}",
                    "path": path,
                    "line_count": line_count,
                    "symbol_count": symbol_count,
                    "excerpt": excerpt[:300],
                    "text": merged,
                }
            )
            if len(docs) >= max_docs:
                break

        return docs

    def _normalize_vector(self, vec: list[float]) -> list[float] | None:
        if not vec:
            return None
        norm = math.sqrt(sum(float(v) * float(v) for v in vec))
        if norm <= 1e-12:
            return None
        return [float(v) / norm for v in vec]

    def _sanitize_semantic_text(self, text: str, *, max_chars: int = 3000) -> str:
        if not text:
            return ""

        cleaned = str(text)
        cleaned = _DATA_URL_RE.sub("[[data_url_omitted]]", cleaned)
        cleaned = _LONG_BASE64_RE.sub("[[base64_blob_omitted]]", cleaned)
        cleaned = _LONG_HEX_RE.sub("[[hex_blob_omitted]]", cleaned)
        cleaned = _LONG_URL_RE.sub("[[long_url_omitted]]", cleaned)
        cleaned = re.sub(r"(?i)<script\b[^>]*>", "[[script_tag]]", cleaned)
        cleaned = re.sub(r"(?i)</script>", "[[/script_tag]]", cleaned)
        cleaned = re.sub(r"(?i)javascript:", "[[javascript_proto]]", cleaned)
        cleaned = cleaned.replace("<", " ").replace(">", " ")

        compact_lines: list[str] = []
        for line in cleaned.splitlines():
            line = line.strip()
            if not line:
                continue
            if len(line) > 260:
                line = f"{line[:220]} ...[truncated]"
            compact_lines.append(line)

        if compact_lines:
            cleaned = "\n".join(compact_lines)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

        hard_cap = max(80, min(max_chars, 3000))
        return cleaned[:hard_cap]

    async def _embed_documents(
        self,
        *,
        docs: list[dict[str, Any]],
        embed_many: Callable[[list[str]], Awaitable[list[list[float]]]],
        embed_one: Callable[[str], Awaitable[list[float]]] | None = None,
        batch_size: int = 16,
    ) -> tuple[list[dict[str, Any]], list[list[float]], list[dict[str, str]]]:
        if not docs:
            return [], [], []

        chunk_size = max(1, min(int(batch_size), 64))
        selected_docs: list[dict[str, Any]] = []
        vectors: list[list[float]] = []
        skipped_docs: list[dict[str, str]] = []

        for start in range(0, len(docs), chunk_size):
            chunk_docs = docs[start : start + chunk_size]
            texts = [str(doc.get("text", "")) for doc in chunk_docs]
            try:
                chunk_vectors = await embed_many(texts)
                if len(chunk_vectors) != len(chunk_docs):
                    raise ValueError(
                        "Embedding size mismatch in chunk "
                        f"{start // chunk_size}: docs={len(chunk_docs)}, vectors={len(chunk_vectors)}"
                    )
                for doc, vec in zip(chunk_docs, chunk_vectors):
                    selected_docs.append(doc)
                    vectors.append([float(v) for v in vec])
                continue
            except Exception as exc:
                if embed_one is None:
                    raise
                err_preview = re.sub(r"\s+", " ", str(exc or "")).strip()[:260]
                logger.warning(
                    "Semantic embedding chunk %s failed, fallback to single-document mode: %s",
                    start // chunk_size,
                    err_preview,
                )

            for doc in chunk_docs:
                try:
                    vec = await embed_one(str(doc.get("text", "")))
                    selected_docs.append(doc)
                    vectors.append([float(v) for v in vec])
                except Exception as item_exc:
                    skipped_docs.append(
                        {
                            "path": str(doc.get("path", "")),
                            "reason": str(item_exc)[:180],
                        }
                    )

        return selected_docs, vectors, skipped_docs

    def _load_semantic_index(self) -> dict[str, Any]:
        if not self.semantic_index_file.exists():
            raise FileNotFoundError(
                "Semantic index not found. Build with astrbot_project_semantic_index_build first."
            )
        return json.loads(self.semantic_index_file.read_text(encoding="utf-8"))

    def get_semantic_index_info(self) -> dict[str, Any]:
        data = self._load_semantic_index()
        stats = data.get("stats") or {}
        return {
            "schema_version": data.get("schema_version"),
            "built_at": data.get("built_at"),
            "source_index_built_at": data.get("source_index_built_at"),
            "provider_id": data.get("provider_id"),
            "provider_model": data.get("provider_model"),
            "dimension": data.get("dimension"),
            "stats": {
                "doc_count": int(stats.get("doc_count", 0) or 0),
                "requested_docs": int(stats.get("requested_docs", 0) or 0),
                "max_docs": int(stats.get("max_docs", 0) or 0),
                "max_doc_chars": int(stats.get("max_doc_chars", 0) or 0),
                "path_prefix": stats.get("path_prefix") or "",
                "skipped_docs": int(stats.get("skipped_docs", 0) or 0),
                "skip_reason_samples": stats.get("skip_reason_samples") or [],
            },
        }

    async def build_semantic_index(
        self,
        *,
        embed_many: Callable[[list[str]], Awaitable[list[list[float]]]],
        provider_id: str,
        provider_model: str = "",
        max_docs: int = 1800,
        max_doc_chars: int = 1200,
        path_prefix: str | None = None,
        embed_one: Callable[[str], Awaitable[list[float]]] | None = None,
        batch_size: int = 16,
    ) -> dict[str, Any]:
        index_data = self._load_index()
        docs = self._build_semantic_documents(
            index_data=index_data,
            max_docs=max(20, min(max_docs, 5000)),
            max_doc_chars=max(200, min(max_doc_chars, 3000)),
            path_prefix=path_prefix,
        )
        if not docs:
            raise ValueError("No files available for semantic indexing.")

        selected_docs, vectors, skipped_docs = await self._embed_documents(
            docs=docs,
            embed_many=embed_many,
            embed_one=embed_one,
            batch_size=batch_size,
        )
        if not selected_docs:
            raise ValueError("No valid vectors generated for semantic index.")

        stored_docs: list[dict[str, Any]] = []
        dim = 0
        for doc, vec in zip(selected_docs, vectors):
            normed = self._normalize_vector(vec)
            if not normed:
                continue
            if dim == 0:
                dim = len(normed)
            if len(normed) != dim:
                continue

            stored_docs.append(
                {
                    "doc_id": doc["doc_id"],
                    "path": doc["path"],
                    "line_count": doc["line_count"],
                    "symbol_count": doc["symbol_count"],
                    "excerpt": doc["excerpt"],
                    "vector": [round(v, 7) for v in normed],
                }
            )

        if not stored_docs:
            raise ValueError("No valid vectors generated for semantic index.")

        if skipped_docs:
            logger.warning(
                "Semantic index build skipped %s documents due provider rejection/errors.",
                len(skipped_docs),
            )

        payload = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "source_index_built_at": index_data.get("built_at"),
            "provider_id": provider_id,
            "provider_model": provider_model,
            "dimension": dim,
            "stats": {
                "doc_count": len(stored_docs),
                "requested_docs": len(docs),
                "max_docs": max_docs,
                "max_doc_chars": max_doc_chars,
                "path_prefix": path_prefix or "",
                "skipped_docs": len(skipped_docs),
                "skip_reason_samples": skipped_docs[:20],
            },
            "docs": stored_docs,
        }

        self.semantic_index_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "doc_count": len(stored_docs),
            "requested_docs": len(docs),
            "skipped_docs": len(skipped_docs),
            "skip_reason_samples": skipped_docs[:20],
            "dimension": dim,
            "provider_id": provider_id,
            "provider_model": provider_model,
            "path_prefix": path_prefix or "",
            "built_at": payload["built_at"],
        }

    async def semantic_search(
        self,
        *,
        query: str,
        embed_one: Callable[[str], Awaitable[list[float]]],
        top_k: int = 8,
        path_prefix: str | None = None,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []

        index_data = self._load_semantic_index()
        docs = index_data.get("docs", [])
        if not docs:
            return []

        query_vec = await embed_one(query)
        normed_query = self._normalize_vector([float(v) for v in query_vec])
        if not normed_query:
            return []

        dim = int(index_data.get("dimension", 0) or 0)
        if dim and dim != len(normed_query):
            raise ValueError(
                f"Embedding dimension mismatch, query={len(normed_query)} semantic_index={dim}"
            )

        prefix = path_prefix.strip("/") if path_prefix else ""
        query_lower = query.lower()

        scored: list[dict[str, Any]] = []
        for doc in docs:
            path = str(doc.get("path", ""))
            if not path:
                continue
            if prefix and not path.startswith(prefix):
                continue

            vec = doc.get("vector")
            if not isinstance(vec, list):
                continue
            if len(vec) != len(normed_query):
                continue

            score = sum(float(v) * q for v, q in zip(vec, normed_query))
            lexical_bonus = 0.0
            if query_lower in path.lower():
                lexical_bonus += 0.04
            if query_lower in str(doc.get("excerpt", "")).lower():
                lexical_bonus += 0.02

            scored.append(
                {
                    "score": round(score + lexical_bonus, 6),
                    "semantic_score": round(score, 6),
                    "path": path,
                    "line_count": int(doc.get("line_count", 0) or 0),
                    "symbol_count": int(doc.get("symbol_count", 0) or 0),
                    "excerpt": str(doc.get("excerpt", "") or "")[:320],
                }
            )

        scored.sort(key=lambda item: (-float(item["score"]), item["path"]))
        return scored[: max(1, min(top_k, 50))]


project_index_manager = ProjectIndexManager()

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

try:
    import chardet
except Exception:  # pragma: no cover - optional dependency import guard
    chardet = None

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

_SYMBOL_PARSE_EXTS = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".md",
    ".rst",
}

_JS_TS_SOURCE_EXTS = {
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".vue",
}

_JS_TS_RESOLVE_EXTS = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".d.ts",
    ".vue",
    ".json",
)

_JS_TS_INDEX_BASENAMES = (
    "index.ts",
    "index.tsx",
    "index.js",
    "index.jsx",
    "index.mjs",
    "index.cjs",
    "index.vue",
    "index.json",
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

    def _normalize_path_key(self, value: str | None) -> str:
        normalized = str(value or "").strip().replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = re.sub(r"/{2,}", "/", normalized)
        parts: list[str] = []
        for part in normalized.split("/"):
            clean = part.strip()
            if not clean or clean == ".":
                continue
            if clean == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(clean)
        return "/".join(parts).strip("/")

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
        resolved_root = root.resolve()
        resolved_file = abs_path.resolve()
        try:
            return resolved_file.relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise ValueError(
                f"Path escaped scan root: {resolved_file.as_posix()}"
            ) from exc

    def _is_likely_text(self, text: str) -> bool:
        sample = text[:2000]
        if not sample:
            return True
        printable = sum(
            1 for char in sample if char.isprintable() or char in {"\n", "\r", "\t"}
        )
        return (printable / len(sample)) >= 0.78

    def _read_text(self, path: Path) -> str:
        raw = path.read_bytes()
        if not raw:
            return ""

        for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
            try:
                decoded = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            if self._is_likely_text(decoded):
                return decoded

        if b"\x00" in raw[:4096]:
            raise ValueError("binary_or_non_text_payload")

        if chardet is not None:
            detected = chardet.detect(raw[:200_000])
            detected_encoding = str((detected or {}).get("encoding") or "").strip()
            confidence = float((detected or {}).get("confidence") or 0.0)
            if detected_encoding and confidence >= 0.55:
                try:
                    decoded = raw.decode(detected_encoding)
                except (LookupError, UnicodeDecodeError):
                    decoded = ""
                if decoded and self._is_likely_text(decoded):
                    return decoded

        for encoding in ("gb18030", "cp1252", "latin-1"):
            try:
                decoded = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            if self._is_likely_text(decoded):
                return decoded

        return raw.decode("utf-8", errors="replace")

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
                for alias in node.names:
                    alias_name = str(alias.name or "").strip()
                    if not alias_name or alias_name == "*":
                        continue
                    if module:
                        imports.append(f"{dots}{module}.{alias_name}")
                    else:
                        imports.append(f"{dots}{alias_name}")
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
            r"import\s+['\"]([^'\"]+)['\"]",
            r"import\(\s*['\"]([^'\"]+)['\"]\s*\)",
            r"require\(\s*['\"]([^'\"]+)['\"]\s*\)",
            r"export\s+\*\s+from\s+['\"]([^'\"]+)['\"]",
            r"export\s+\{[^}]*\}\s+from\s+['\"]([^'\"]+)['\"]",
        ]
        symbol_patterns = [
            (
                "class",
                r"(?:export\s+default\s+|export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)",
            ),
            (
                "function",
                r"(?:export\s+default\s+|export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            ),
            (
                "function",
                r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
            ),
            (
                "function",
                r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?[A-Za-z_$][A-Za-z0-9_$]*\s*=>",
            ),
            (
                "function",
                r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?function\s*\(",
            ),
            ("interface", r"(?:export\s+)?interface\s+([A-Za-z_][A-Za-z0-9_]*)"),
            ("type", r"(?:export\s+)?type\s+([A-Za-z_][A-Za-z0-9_]*)\s*="),
            ("enum", r"(?:export\s+)?enum\s+([A-Za-z_][A-Za-z0-9_]*)"),
        ]

        for pattern in import_patterns:
            for hit in re.findall(pattern, content):
                imports.append(hit)

        seen_symbols: set[tuple[str, str, int]] = set()
        for kind, pattern in symbol_patterns:
            for match in re.finditer(pattern, content):
                line = content[: match.start()].count("\n") + 1
                name = match.group(1)
                key = (name, kind, line)
                if key in seen_symbols:
                    continue
                seen_symbols.add(key)
                symbols.append({"name": name, "kind": kind, "line": line})

        return symbols, imports

    def _parse_markdown(self, content: str) -> list[dict]:
        symbols: list[dict] = []
        for line_no, line in enumerate(content.splitlines(), start=1):
            heading_match = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
            if not heading_match:
                continue
            title = heading_match.group(2).strip()
            if not title:
                continue
            level = len(heading_match.group(1))
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
            up_levels = max(level - 1, 0)
            if up_levels > len(package_parts):
                return None
            prefix = package_parts[: len(package_parts) - up_levels]
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

    def _resolve_local_js_import(
        self,
        import_str: str,
        current_file: str,
        file_map: dict[str, dict[str, Any]],
    ) -> str | None:
        raw = str(import_str or "").strip()
        if not raw:
            return None
        cleaned = raw.split("?", 1)[0].split("#", 1)[0].strip()
        if not cleaned:
            return None

        base_candidates: list[str] = []
        if cleaned.startswith("."):
            current_dir = self._normalize_path_key(str(Path(current_file).parent))
            if current_dir:
                base_candidates.append(f"{current_dir}/{cleaned}")
            else:
                base_candidates.append(cleaned)
        elif cleaned.startswith("@/"):
            base_candidates.append(cleaned[2:])
        elif cleaned.startswith("~/"):
            base_candidates.append(cleaned[2:])
        elif cleaned.startswith("/"):
            base_candidates.append(cleaned)
        else:
            return None

        for base in base_candidates:
            normalized_base = self._normalize_path_key(base)
            if not normalized_base:
                continue
            resolved = self._resolve_local_js_candidate(
                normalized_base=normalized_base,
                file_map=file_map,
            )
            if resolved:
                return resolved
        return None

    def _resolve_local_js_candidate(
        self,
        *,
        normalized_base: str,
        file_map: dict[str, dict[str, Any]],
    ) -> str | None:
        if normalized_base in file_map:
            return normalized_base

        base_path = Path(normalized_base)
        base_suffix = base_path.suffix.lower()
        if base_suffix:
            if normalized_base in file_map:
                return normalized_base

            stem = normalized_base[: -len(base_suffix)]
            if base_suffix in {".js", ".jsx", ".mjs", ".cjs"}:
                for ext in (".ts", ".tsx", ".vue"):
                    alt = f"{stem}{ext}"
                    if alt in file_map:
                        return alt
            elif base_suffix in {".ts", ".tsx"}:
                for ext in (".js", ".jsx", ".mjs", ".cjs", ".vue"):
                    alt = f"{stem}{ext}"
                    if alt in file_map:
                        return alt
        else:
            for ext in _JS_TS_RESOLVE_EXTS:
                candidate = f"{normalized_base}{ext}"
                if candidate in file_map:
                    return candidate

        base_no_tail = normalized_base.rstrip("/")
        for index_name in _JS_TS_INDEX_BASENAMES:
            candidate = f"{base_no_tail}/{index_name}"
            if candidate in file_map:
                return candidate
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
        max_files = self._coerce_int(
            max_files, default=12000, minimum=1, maximum=200000
        )
        max_file_bytes = self._coerce_int(
            max_file_bytes,
            default=1_500_000,
            minimum=1024,
            maximum=20_000_000,
        )
        stats = BuildStats()

        files: list[dict[str, Any]] = []
        module_to_file: dict[str, str] = {}
        line_total = 0
        seen_paths: set[str] = set()

        for curr_root, dir_names, file_names in os.walk(scan_root):
            curr_path = Path(curr_root)
            dir_names[:] = sorted(
                (
                    d
                    for d in dir_names
                    if d not in _DEFAULT_EXCLUDE_DIRS and not d.startswith(".")
                ),
                key=str.lower,
            )

            for file_name in sorted(file_names, key=str.lower):
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
                except ValueError as exc:
                    if "binary_or_non_text_payload" in str(exc):
                        stats.skipped_binary_files += 1
                    continue
                except Exception:
                    continue

                try:
                    rel = self._normalize_path_key(self._to_rel(abs_file, scan_root))
                except ValueError:
                    continue
                if not rel or rel in seen_paths:
                    continue
                seen_paths.add(rel)
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
            elif item["ext"] in _JS_TS_SOURCE_EXTS:
                for import_str in item["imports"]:
                    target = self._resolve_local_js_import(
                        import_str,
                        rel_path,
                        file_map,
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
        try:
            data = json.loads(self.index_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Project index file is corrupted. Rebuild with astrbot_project_index_build."
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(
                "Project index format is invalid. Rebuild with astrbot_project_index_build."
            )
        return data

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

    def get_analysis_scope(self) -> dict[str, Any]:
        scope: dict[str, Any] = {
            "workspace_root": self.workspace_root.as_posix(),
            "default_scan_root": self.workspace_root.as_posix(),
            "supported_text_extensions": sorted(_TEXT_FILE_EXTS),
            "symbol_parse_extensions": sorted(_SYMBOL_PARSE_EXTS),
            "dependency_graph_extensions": sorted({".py", ".pyi", *_JS_TS_SOURCE_EXTS}),
            "exclude_dirs": sorted(_DEFAULT_EXCLUDE_DIRS),
            "exclude_globs": list(_DEFAULT_EXCLUDE_GLOBS),
            "direct_file_allowlist": sorted(_DIRECT_FILE_ALLOWLIST),
            "index_available": False,
            "current_scan_root": "",
            "indexed_file_count": 0,
            "indexed_top_dirs": [],
            "indexed_path_samples": [],
        }

        try:
            index_data = self._load_index()
        except FileNotFoundError:
            return scope
        except Exception as exc:
            scope["index_error"] = str(exc)
            return scope

        files = index_data.get("files", [])
        top_dirs_raw = index_data.get("top_dirs", [])
        top_dirs: list[str] = []
        for item in top_dirs_raw:
            if isinstance(item, (list, tuple)) and item:
                top_dirs.append(str(item[0]))
                continue
            if isinstance(item, dict) and item.get("path"):
                top_dirs.append(str(item.get("path")))

        sample_paths: list[str] = []
        for file_item in files:
            path = self._normalize_path_key(str(file_item.get("path", "")))
            if not path:
                continue
            sample_paths.append(path)
            if len(sample_paths) >= 30:
                break

        scope["index_available"] = True
        scope["current_scan_root"] = str(index_data.get("scan_root") or "")
        scope["indexed_file_count"] = len(files)
        scope["indexed_top_dirs"] = top_dirs[:20]
        scope["indexed_path_samples"] = sample_paths
        return scope

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

        limit = self._coerce_int(limit, default=20, minimum=1, maximum=200)
        prefix = self._normalize_path_key(path_prefix) if path_prefix else ""
        query_tokens = [token for token in re.findall(r"\w+", query_norm) if token]
        results: list[dict[str, Any]] = []

        for item in files:
            file_path = self._normalize_path_key(str(item.get("path", "")))
            if not file_path:
                continue
            if prefix and not file_path.startswith(prefix):
                continue

            for symbol in item.get("symbols", []):
                name = str(symbol.get("name", ""))
                symbol_kind = str(symbol.get("kind", ""))
                if kind and symbol_kind != kind:
                    continue

                name_norm = name.lower()
                token_hits = (
                    sum(1 for token in query_tokens if token in name_norm)
                    if query_tokens
                    else 0
                )
                if query_norm not in name_norm and token_hits == 0:
                    continue

                score = 100
                if name_norm == query_norm:
                    score += 100
                elif name_norm.startswith(query_norm):
                    score += 40
                if name_norm.endswith(query_norm):
                    score += 12
                if query_norm in file_path.lower():
                    score += 10
                if token_hits:
                    score += min(60, token_hits * 12)

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
        return results[:limit]

    def _resolve_indexed_file_path(
        self,
        *,
        file_path: str,
        index_data: dict[str, Any],
    ) -> str:
        graph = index_data.get("graph", {}) or {}
        reverse_graph = index_data.get("reverse_graph", {}) or {}
        all_paths = set(graph.keys()) | set(reverse_graph.keys())

        raw = str(file_path or "").strip()
        if not raw:
            raise ValueError("file_path is required")

        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            scan_root_raw = str(index_data.get("scan_root") or "")
            if scan_root_raw:
                try:
                    scan_root = Path(scan_root_raw).resolve()
                    raw = candidate.resolve().relative_to(scan_root).as_posix()
                except Exception:
                    raw = candidate.name

        normalized = self._normalize_path_key(raw)
        if normalized in all_paths:
            return normalized

        suffix = f"/{normalized}"
        matched = sorted(
            path for path in all_paths if path == normalized or path.endswith(suffix)
        )
        if len(matched) == 1:
            return matched[0]
        if len(matched) > 1:
            preview = ", ".join(matched[:8])
            raise ValueError(f"File path is ambiguous: {normalized}. Candidates: {preview}")
        raise ValueError(f"File not found in index: {normalized}")

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

        max_depth = self._coerce_int(depth, default=2, minimum=1, maximum=6)
        limit_nodes = self._coerce_int(
            limit_nodes, default=200, minimum=20, maximum=2000
        )
        source = self._resolve_indexed_file_path(
            file_path=file_path,
            index_data=index_data,
        )

        adjacency = graph if direction == "outbound" else reverse_graph

        nodes_seen: set[str] = {source}
        edges: list[dict[str, Any]] = []
        queue: deque[tuple[str, int]] = deque([(source, 0)])

        while queue and len(nodes_seen) < limit_nodes:
            current, curr_depth = queue.popleft()
            if curr_depth >= max_depth:
                continue
            neighbors = adjacency.get(current, [])
            if not isinstance(neighbors, list):
                continue
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
        max_docs = self._coerce_int(max_docs, default=1800, minimum=1, maximum=5000)
        max_doc_chars = self._coerce_int(
            max_doc_chars, default=1200, minimum=80, maximum=3000
        )
        prefix = self._normalize_path_key(path_prefix) if path_prefix else ""
        docs: list[dict[str, Any]] = []

        for item in files:
            path = self._normalize_path_key(str(item.get("path", "")).strip())
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
        values: list[float] = []
        for value in vec:
            fv = float(value)
            if not math.isfinite(fv):
                return None
            values.append(fv)

        norm = math.sqrt(sum(v * v for v in values))
        if not math.isfinite(norm) or norm <= 1e-12:
            return None
        return [v / norm for v in values]

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
                    if not isinstance(vec, (list, tuple)):
                        raise ValueError("Embedding vector should be a list of numbers.")
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
                    if not isinstance(vec, (list, tuple)):
                        raise ValueError("Embedding vector should be a list of numbers.")
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
        try:
            data = json.loads(self.semantic_index_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Semantic index file is corrupted. Rebuild with astrbot_project_semantic_index_build."
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(
                "Semantic index format is invalid. Rebuild with astrbot_project_semantic_index_build."
            )
        return data

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
        max_docs = self._coerce_int(max_docs, default=1800, minimum=20, maximum=5000)
        max_doc_chars = self._coerce_int(
            max_doc_chars, default=1200, minimum=200, maximum=3000
        )
        batch_size = self._coerce_int(batch_size, default=16, minimum=1, maximum=64)
        path_prefix_norm = self._normalize_path_key(path_prefix) if path_prefix else None

        index_data = self._load_index()
        docs = self._build_semantic_documents(
            index_data=index_data,
            max_docs=max_docs,
            max_doc_chars=max_doc_chars,
            path_prefix=path_prefix_norm,
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
        vector_skip_samples: list[dict[str, str]] = []
        vector_skipped = 0
        dim = 0
        for doc, vec in zip(selected_docs, vectors):
            normed = self._normalize_vector(vec)
            if not normed:
                vector_skipped += 1
                if len(vector_skip_samples) < 20:
                    vector_skip_samples.append(
                        {
                            "path": str(doc.get("path", "")),
                            "reason": "invalid_or_zero_norm_vector",
                        }
                    )
                continue
            if dim == 0:
                dim = len(normed)
            if len(normed) != dim:
                vector_skipped += 1
                if len(vector_skip_samples) < 20:
                    vector_skip_samples.append(
                        {
                            "path": str(doc.get("path", "")),
                            "reason": "dimension_mismatch_vector",
                        }
                    )
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

        total_skipped = len(skipped_docs) + vector_skipped
        skip_reason_samples = (skipped_docs + vector_skip_samples)[:20]
        if total_skipped:
            logger.warning(
                "Semantic index build skipped %s documents due provider rejection/errors.",
                total_skipped,
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
                "path_prefix": path_prefix_norm or "",
                "skipped_docs": total_skipped,
                "skip_reason_samples": skip_reason_samples,
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
            "skipped_docs": total_skipped,
            "skip_reason_samples": skip_reason_samples,
            "dimension": dim,
            "provider_id": provider_id,
            "provider_model": provider_model,
            "path_prefix": path_prefix_norm or "",
            "built_at": payload["built_at"],
        }

    def _semantic_query_tokens(self, query: str) -> list[str]:
        seen: set[str] = set()
        tokens: list[str] = []
        for token in re.findall(r"\w+", query.lower()):
            normalized = token.strip()
            if not normalized:
                continue
            if len(normalized) == 1 and normalized.isascii():
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            tokens.append(normalized)
            if len(tokens) >= 12:
                break
        return tokens

    def _semantic_lexical_bonus(
        self,
        *,
        query_lower: str,
        query_tokens: list[str],
        path: str,
        excerpt: str,
    ) -> float:
        path_lower = path.lower()
        excerpt_lower = excerpt.lower()
        bonus = 0.0
        if query_lower and query_lower in path_lower:
            bonus += 0.06
        if query_lower and query_lower in excerpt_lower:
            bonus += 0.04
        if query_tokens:
            token_hits = sum(
                1 for token in query_tokens if token in path_lower or token in excerpt_lower
            )
            coverage = token_hits / len(query_tokens)
            bonus += min(0.08, coverage * 0.08)
        return bonus

    def _semantic_lexical_search(
        self,
        *,
        docs: list[dict[str, Any]],
        query: str,
        top_k: int,
        path_prefix: str | None,
    ) -> list[dict[str, Any]]:
        top_k = self._coerce_int(top_k, default=8, minimum=1, maximum=50)
        prefix = self._normalize_path_key(path_prefix) if path_prefix else ""
        query_lower = query.lower()
        query_tokens = self._semantic_query_tokens(query)

        scored: list[dict[str, Any]] = []
        for doc in docs:
            path = self._normalize_path_key(str(doc.get("path", "")))
            if not path:
                continue
            if prefix and not path.startswith(prefix):
                continue
            excerpt = str(doc.get("excerpt", "") or "")[:320]
            lexical_bonus = self._semantic_lexical_bonus(
                query_lower=query_lower,
                query_tokens=query_tokens,
                path=path,
                excerpt=excerpt,
            )
            if lexical_bonus <= 0:
                continue
            scored.append(
                {
                    "score": round(lexical_bonus, 6),
                    "semantic_score": 0.0,
                    "path": path,
                    "line_count": int(doc.get("line_count", 0) or 0),
                    "symbol_count": int(doc.get("symbol_count", 0) or 0),
                    "excerpt": excerpt,
                }
            )

        scored.sort(key=lambda item: (-float(item["score"]), item["path"]))
        return scored[:top_k]

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
        top_k = self._coerce_int(top_k, default=8, minimum=1, maximum=50)

        index_data = self._load_semantic_index()
        docs = index_data.get("docs", [])
        if not docs:
            return []

        try:
            query_vec = await embed_one(query)
            normed_query = self._normalize_vector([float(v) for v in query_vec])
        except Exception as exc:
            logger.warning(
                "Semantic query embedding failed, fallback to lexical ranking: %s",
                str(exc)[:220],
            )
            return self._semantic_lexical_search(
                docs=docs,
                query=query,
                top_k=top_k,
                path_prefix=path_prefix,
            )
        if not normed_query:
            return []

        dim = int(index_data.get("dimension", 0) or 0)
        if dim and dim != len(normed_query):
            logger.warning(
                "Semantic search dimension mismatch query=%s index=%s, fallback lexical.",
                len(normed_query),
                dim,
            )
            return self._semantic_lexical_search(
                docs=docs,
                query=query,
                top_k=top_k,
                path_prefix=path_prefix,
            )

        prefix = self._normalize_path_key(path_prefix) if path_prefix else ""
        query_lower = query.lower()
        query_tokens = self._semantic_query_tokens(query)

        scored: list[dict[str, Any]] = []
        for doc in docs:
            path = self._normalize_path_key(str(doc.get("path", "")))
            if not path:
                continue
            if prefix and not path.startswith(prefix):
                continue

            vec = doc.get("vector")
            if not isinstance(vec, list):
                continue
            try:
                vector = [float(value) for value in vec]
            except (TypeError, ValueError):
                continue
            if len(vector) != len(normed_query):
                continue
            if not all(math.isfinite(value) for value in vector):
                continue

            score = sum(value * q for value, q in zip(vector, normed_query))
            if not math.isfinite(score):
                continue
            excerpt = str(doc.get("excerpt", "") or "")[:320]
            lexical_bonus = self._semantic_lexical_bonus(
                query_lower=query_lower,
                query_tokens=query_tokens,
                path=path,
                excerpt=excerpt,
            )

            scored.append(
                {
                    "score": round(score + lexical_bonus, 6),
                    "semantic_score": round(score, 6),
                    "path": path,
                    "line_count": int(doc.get("line_count", 0) or 0),
                    "symbol_count": int(doc.get("symbol_count", 0) or 0),
                    "excerpt": excerpt,
                }
            )

        if not scored:
            return self._semantic_lexical_search(
                docs=docs,
                query=query,
                top_k=top_k,
                path_prefix=path_prefix,
            )
        scored.sort(key=lambda item: (-float(item["score"]), item["path"]))
        return scored[:top_k]


project_index_manager = ProjectIndexManager()

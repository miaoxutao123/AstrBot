from pathlib import Path

import pytest

from astrbot.core.project_context.index_manager import ProjectIndexManager


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_project_index_build_and_query(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))

    _write(
        tmp_path / "app" / "main.py",
        "from pkg.utils import helper\n\n\ndef run():\n    return helper()\n",
    )
    _write(
        tmp_path / "pkg" / "__init__.py",
        "",
    )
    _write(
        tmp_path / "pkg" / "utils.py",
        "def helper():\n    return 'ok'\n",
    )
    _write(
        tmp_path / "README.md",
        "# Demo Project\n\n## Usage\n",
    )

    manager = ProjectIndexManager(workspace_root=str(tmp_path))
    result = manager.build_index(
        root=str(tmp_path), max_files=100, max_file_bytes=200000
    )

    assert result["indexed_files"] >= 4

    symbol_hits = manager.search_symbols(query="helper", limit=10)
    assert any(hit["path"] == "pkg/utils.py" for hit in symbol_hits)

    dep = manager.trace_dependency(
        file_path="app/main.py",
        direction="outbound",
        depth=2,
    )
    assert "pkg/utils.py" in dep["nodes"]

    summary = manager.architecture_summary(top_n=5)
    heavy_paths = {item["path"] for item in summary["heavy_files"]}
    assert "app/main.py" in heavy_paths


def test_project_index_relative_import_resolution_and_path_compat(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))

    _write(
        tmp_path / "pkg" / "__init__.py",
        "",
    )
    _write(
        tmp_path / "pkg" / "service.py",
        "from .utils import helper\n\n\ndef run():\n    return helper()\n",
    )
    _write(
        tmp_path / "pkg" / "utils.py",
        "def helper():\n    return 'ok'\n",
    )

    manager = ProjectIndexManager(workspace_root=str(tmp_path))
    manager.build_index(root=str(tmp_path), max_files=100, max_file_bytes=200000)

    dep_windows = manager.trace_dependency(
        file_path=r"pkg\service.py",
        direction="outbound",
        depth=2,
    )
    assert dep_windows["source"] == "pkg/service.py"
    assert "pkg/utils.py" in dep_windows["nodes"]

    dep_abs = manager.trace_dependency(
        file_path=str(tmp_path / "pkg" / "service.py"),
        direction="outbound",
        depth=2,
    )
    assert dep_abs["source"] == "pkg/service.py"
    assert "pkg/utils.py" in dep_abs["nodes"]


def test_project_index_decode_utf16_and_gb18030(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))

    utf16 = tmp_path / "docs" / "utf16.txt"
    utf16.parent.mkdir(parents=True, exist_ok=True)
    utf16.write_bytes("utf16 file with retry strategy".encode("utf-16"))

    gbk = tmp_path / "docs" / "gbk.txt"
    gbk.write_bytes("中文编码文件".encode("gb18030"))

    manager = ProjectIndexManager(workspace_root=str(tmp_path))
    manager.build_index(root=str(tmp_path), max_files=100, max_file_bytes=200000)

    files = manager._load_index().get("files", [])
    indexed_paths = {item["path"] for item in files}
    assert "docs/utf16.txt" in indexed_paths
    assert "docs/gbk.txt" in indexed_paths


def test_project_index_js_ts_symbol_and_import_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))

    _write(
        tmp_path / "web" / "src" / "store.ts",
        (
            'import { api } from "./api"\n'
            'import "./polyfill"\n'
            "export const useStore = (state) => state\n"
            "const pick = value => value\n"
            "const legacy = function () { return null }\n"
            "export interface AppState { id: string }\n"
            "export type UserId = string\n"
            "export enum Mode { Auto = 'auto' }\n"
        ),
    )
    _write(tmp_path / "web" / "src" / "api.ts", "export const api = {}")

    manager = ProjectIndexManager(workspace_root=str(tmp_path))
    manager.build_index(root=str(tmp_path), max_files=100, max_file_bytes=200000)

    files = manager._load_index().get("files", [])
    store_file = next(item for item in files if item["path"] == "web/src/store.ts")
    imports = set(store_file.get("imports", []))
    assert "./api" in imports
    assert "./polyfill" in imports

    symbol_pairs = {(sym["name"], sym["kind"]) for sym in store_file.get("symbols", [])}
    assert ("useStore", "function") in symbol_pairs
    assert ("pick", "function") in symbol_pairs
    assert ("legacy", "function") in symbol_pairs
    assert ("AppState", "interface") in symbol_pairs
    assert ("UserId", "type") in symbol_pairs
    assert ("Mode", "enum") in symbol_pairs


def test_project_index_js_dependency_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))

    _write(
        tmp_path / "web" / "src" / "main.ts",
        (
            'import { helper } from "./utils"\n'
            'import { shared } from "@/shared/index"\n'
            "export const run = () => helper + shared\n"
        ),
    )
    _write(tmp_path / "web" / "src" / "utils.ts", "export const helper = 1")
    _write(tmp_path / "shared" / "index.ts", "export const shared = 2")

    manager = ProjectIndexManager(workspace_root=str(tmp_path))
    manager.build_index(root=str(tmp_path), max_files=100, max_file_bytes=200000)

    dep = manager.trace_dependency(
        file_path="web/src/main.ts",
        direction="outbound",
        depth=2,
    )
    assert "web/src/utils.ts" in dep["nodes"]
    assert "shared/index.ts" in dep["nodes"]


def test_project_index_markdown_heading_compat(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))

    _write(
        tmp_path / "docs" / "guide.md",
        "   ## Overview ##\n### Details\n",
    )

    manager = ProjectIndexManager(workspace_root=str(tmp_path))
    manager.build_index(root=str(tmp_path), max_files=100, max_file_bytes=200000)

    hits = manager.search_symbols(query="overview", kind="heading_h2")
    assert any(hit["path"] == "docs/guide.md" for hit in hits)


def test_project_index_analysis_scope_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))

    manager = ProjectIndexManager(workspace_root=str(tmp_path))
    scope_before = manager.get_analysis_scope()
    assert scope_before["index_available"] is False
    assert ".py" in scope_before["symbol_parse_extensions"]
    assert ".ts" in scope_before["dependency_graph_extensions"]

    _write(tmp_path / "src" / "app.py", "def run():\n    return 1\n")
    manager.build_index(root=str(tmp_path), max_files=100, max_file_bytes=200000)

    scope_after = manager.get_analysis_scope()
    assert scope_after["index_available"] is True
    assert scope_after["current_scan_root"] == tmp_path.as_posix()
    assert scope_after["indexed_file_count"] >= 1
    assert any(path == "src/app.py" for path in scope_after["indexed_path_samples"])
    assert any(dir_name == "src" for dir_name in scope_after["indexed_top_dirs"])


@pytest.mark.asyncio
async def test_project_semantic_index_build_and_search(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))

    _write(
        tmp_path / "dashboard" / "src" / "views" / "chat.vue",
        "chat composer state manager and websocket reconnect strategy",
    )
    _write(
        tmp_path / "dashboard" / "src" / "views" / "ops.vue",
        "background retry control panel and task observability dashboard",
    )

    manager = ProjectIndexManager(workspace_root=str(tmp_path))
    manager.build_index(root=str(tmp_path), max_files=100, max_file_bytes=200000)

    def _embed_text(text: str) -> list[float]:
        text = text.lower()
        keywords = [
            "chat",
            "websocket",
            "retry",
            "dashboard",
            "task",
            "state",
        ]
        return [float(text.count(keyword)) for keyword in keywords]

    async def embed_many(texts: list[str]) -> list[list[float]]:
        return [_embed_text(text) for text in texts]

    async def embed_one(text: str) -> list[float]:
        return _embed_text(text)

    build_result = await manager.build_semantic_index(
        embed_many=embed_many,
        provider_id="test_embedding",
        provider_model="test-model",
        max_docs=20,
        max_doc_chars=400,
        path_prefix="dashboard/src",
    )
    assert build_result["doc_count"] >= 2

    info = manager.get_semantic_index_info()
    assert info["provider_id"] == "test_embedding"

    hits = await manager.semantic_search(
        query="retry task dashboard",
        embed_one=embed_one,
        top_k=5,
        path_prefix="dashboard/src",
    )
    assert hits
    assert any("ops.vue" in item["path"] for item in hits)


@pytest.mark.asyncio
async def test_project_semantic_index_build_fallback_and_skip(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))

    _write(
        tmp_path / "dashboard" / "src" / "safe_doc.vue",
        "safe semantic snippet for frontend state and routing",
    )
    _write(
        tmp_path / "dashboard" / "src" / "blocked_doc.vue",
        "blocked semantic snippet that provider may reject",
    )

    manager = ProjectIndexManager(workspace_root=str(tmp_path))
    manager.build_index(root=str(tmp_path), max_files=100, max_file_bytes=200000)

    async def embed_many(texts: list[str]) -> list[list[float]]:
        if len(texts) > 1:
            raise Exception("provider blocked batch as malicious parameter")
        return [[float(len(texts[0]))]]

    async def embed_one(text: str) -> list[float]:
        if "blocked_doc.vue" in text:
            raise Exception("malicious parameter blocked")
        return [float(len(text))]

    result = await manager.build_semantic_index(
        embed_many=embed_many,
        embed_one=embed_one,
        provider_id="test_embedding",
        provider_model="test-model",
        max_docs=20,
        max_doc_chars=400,
        path_prefix="dashboard/src",
    )

    assert result["doc_count"] == 1
    assert result["skipped_docs"] == 1
    assert result["skip_reason_samples"]
    assert result["skip_reason_samples"][0]["path"].endswith("blocked_doc.vue")

    info = manager.get_semantic_index_info()
    assert info["stats"]["skipped_docs"] == 1


@pytest.mark.asyncio
async def test_project_semantic_search_dimension_mismatch_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))

    _write(
        tmp_path / "dashboard" / "src" / "ops.vue",
        "retry task dashboard observability",
    )
    _write(
        tmp_path / "dashboard" / "src" / "chat.vue",
        "chat state websocket connection manager",
    )

    manager = ProjectIndexManager(workspace_root=str(tmp_path))
    manager.build_index(root=str(tmp_path), max_files=100, max_file_bytes=200000)

    async def embed_many(texts: list[str]) -> list[list[float]]:
        return [
            [float("retry" in text.lower()), float("chat" in text.lower())]
            for text in texts
        ]

    async def embed_one_dim3(_: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    await manager.build_semantic_index(
        embed_many=embed_many,
        provider_id="test_embedding",
        provider_model="test-model",
        max_docs=20,
        max_doc_chars=400,
        path_prefix="dashboard/src",
    )

    hits = await manager.semantic_search(
        query="ops retry",
        embed_one=embed_one_dim3,
        top_k=5,
        path_prefix=r"dashboard\src",
    )
    assert hits
    assert any("ops.vue" in item["path"] for item in hits)
    assert all(item["semantic_score"] == 0.0 for item in hits)


def test_project_semantic_documents_sanitize_long_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))

    long_data = "data:image/png;base64," + ("A" * 420)
    _write(
        tmp_path / "dashboard" / "index.html",
        f'<link rel="icon" href="{long_data}" />',
    )

    manager = ProjectIndexManager(workspace_root=str(tmp_path))
    manager.build_index(root=str(tmp_path), max_files=100, max_file_bytes=200000)

    docs = manager._build_semantic_documents(
        index_data=manager._load_index(),
        max_docs=20,
        max_doc_chars=800,
        path_prefix="dashboard",
    )

    assert docs
    payload = next(doc for doc in docs if doc["path"] == "dashboard/index.html")
    assert "data:image/png;base64" not in payload["text"]
    assert (
        "[[data_url_omitted]]" in payload["text"]
        or "[[base64_blob_omitted]]" in payload["text"]
    )

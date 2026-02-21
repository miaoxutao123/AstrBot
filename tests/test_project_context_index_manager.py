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

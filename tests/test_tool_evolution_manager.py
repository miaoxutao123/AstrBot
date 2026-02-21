import pytest

from astrbot.core.tool_evolution.manager import ToolEvolutionManager


@pytest.mark.asyncio
async def test_tool_evolution_apply_and_auto_rollback(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    manager = ToolEvolutionManager()

    tool_name = "demo_tool"
    timeout_failure_seqs = {2, 5, 6, 10, 11, 14}
    bad_arg_failure_seqs = {3, 7, 12}

    for seq in range(1, 17):
        if seq in timeout_failure_seqs:
            success = False
            error = "tool execution timeout after 60 seconds"
        elif seq in bad_arg_failure_seqs:
            success = False
            error = "TypeError: got an unexpected keyword argument 'bad_arg'"
        else:
            success = True
            error = ""

        await manager.record_tool_call(
            tool_name=tool_name,
            success=success,
            args={"good": 1, "bad_arg": 2},
            error=error,
            duration_s=0.2,
        )

    proposal = await manager.propose_policy(tool_name)
    assert proposal["ok"] is True

    actions = proposal["candidate"]["actions"]
    assert actions

    applied = await manager.apply_policy(tool_name, dry_run=False)
    assert applied["ok"] is True
    assert applied["action"] in {"applied", "noop"}

    adapted = await manager.adapt_tool_call(
        tool_name=tool_name,
        args={"good": 1, "bad_arg": 2, "unexpected": 3},
        default_timeout=10,
        expected_params=["good", "bad_arg"],
    )

    if "blocked_args" in actions:
        assert "bad_arg" not in adapted["args"]

    for _ in range(manager.guardrails.rollback_min_window):
        await manager.record_tool_call(
            tool_name=tool_name,
            success=False,
            args={"good": 1},
            error="timeout after apply",
            duration_s=0.2,
        )

    overview = await manager.get_overview(tool_name=tool_name, window=100)
    assert overview["tools"]
    assert overview["tools"][0]["active_policy"] is False


@pytest.mark.asyncio
async def test_tool_evolution_auto_apply_preview(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    manager = ToolEvolutionManager()

    tool_name = "auto_tool"
    for seq in range(1, 13):
        success = seq % 3 != 0
        error = ""
        if not success:
            error = "tool execution timeout"
        await manager.record_tool_call(
            tool_name=tool_name,
            success=success,
            args={"k": seq},
            error=error,
            duration_s=0.1,
        )

    result = await manager.maybe_auto_apply(
        tool_name=tool_name,
        min_samples=12,
        dry_run=True,
        every_n_calls=6,
    )
    assert result is not None
    assert result.get("auto_apply") is True


@pytest.mark.asyncio
async def test_tool_evolution_persist_is_throttled(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    manager = ToolEvolutionManager()

    persist_calls = 0

    def _fake_persist():
        nonlocal persist_calls
        persist_calls += 1

    manager._persist = _fake_persist  # type: ignore[method-assign]

    for idx in range(10):
        await manager.record_tool_call(
            tool_name="persist_tool",
            success=True,
            args={"i": idx},
            error="",
            duration_s=0.01,
        )

    assert persist_calls >= 1
    assert persist_calls <= 3


@pytest.mark.asyncio
async def test_tool_evolution_auto_apply_marker_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    manager = ToolEvolutionManager()
    tool_name = "marker_tool"

    for seq in range(1, 13):
        success = seq % 3 != 0
        error = "" if success else "tool execution timeout"
        await manager.record_tool_call(
            tool_name=tool_name,
            success=success,
            args={"k": seq},
            error=error,
            duration_s=0.1,
        )

    result = await manager.maybe_auto_apply(
        tool_name=tool_name,
        min_samples=12,
        dry_run=True,
        every_n_calls=6,
    )
    assert result is not None
    assert manager._auto_apply_markers.get(tool_name) == 12

    reloaded = ToolEvolutionManager()
    assert reloaded._auto_apply_markers.get(tool_name) == 12


@pytest.mark.asyncio
async def test_tool_evolution_record_tool_call_compacts_large_args(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    manager = ToolEvolutionManager()

    huge_args = {
        "very_long_text": "x" * 2000,
        "nested": {
            "inner_text": "y" * 1000,
            "deep": {"value": "z" * 1000},
        },
        "many_items": list(range(100)),
    }
    await manager.record_tool_call(
        tool_name="compact_tool",
        success=False,
        args=huge_args,
        error="TypeError: got an unexpected keyword argument 'bad_arg'",
        duration_s=0.12,
    )

    overview = await manager.get_overview(tool_name="compact_tool", window=20)
    assert overview["window"] >= 1
    assert manager._calls
    row = manager._calls[-1]
    assert isinstance(row.get("args"), dict)
    compacted = row["args"]
    assert len(compacted.get("very_long_text", "")) < 400

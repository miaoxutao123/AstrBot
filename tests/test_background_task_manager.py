import asyncio

import pytest

from astrbot.core.runtime.background_task_manager import (
    BackgroundTaskManager,
    RetryPolicy,
)


@pytest.mark.asyncio
async def test_background_task_retry_then_success(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    manager = BackgroundTaskManager()

    task_id = await manager.create_task(
        tool_name="demo_tool",
        session_id="session-a",
        tool_args={"q": "x"},
        retry_policy=RetryPolicy(
            max_attempts=3,
            base_backoff_seconds=0.01,
            max_backoff_seconds=0.01,
        ),
    )

    async def attempt_runner(attempt_no: int) -> str:
        if attempt_no < 3:
            raise RuntimeError("timeout while upstream is unavailable")
        return "done"

    snapshot = await manager.run_with_retry(
        task_id=task_id,
        attempt_runner=attempt_runner,
    )

    assert snapshot["status"] == "succeeded"
    assert snapshot["attempt"] == 3
    assert snapshot["result"] == "done"


@pytest.mark.asyncio
async def test_background_task_cancel(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    manager = BackgroundTaskManager()

    task_id = await manager.create_task(
        tool_name="demo_tool",
        session_id="session-a",
        tool_args={},
    )
    runtime_task = asyncio.create_task(asyncio.sleep(30))
    await manager.attach_runtime_task(task_id, runtime_task)

    ok = await manager.cancel_task(task_id)
    assert ok is True

    task = await manager.get_task(task_id)
    assert task
    assert task["status"] == "cancelled"

    try:
        await runtime_task
    except asyncio.CancelledError:
        pass

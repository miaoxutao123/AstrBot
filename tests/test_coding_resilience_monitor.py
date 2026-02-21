import pytest

from astrbot.core.runtime.resilience_monitor import CodingResilienceMonitor


@pytest.mark.asyncio
async def test_coding_resilience_monitor_record_and_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path))
    monitor = CodingResilienceMonitor()

    await monitor.record_event(event="llm_retry", detail="attempt 1")
    await monitor.record_event(event="step_retry", detail="step retry")
    await monitor.record_event(event="stream_fallback", detail="stream fallback")
    await monitor.record_event(event="recovered", detail="recovered")
    await monitor.record_event(event="failed", detail="429 too many requests")

    snapshot = await monitor.get_snapshot()
    stats = snapshot["stats"]
    assert stats["llm_retry_count"] == 1
    assert stats["step_retry_count"] == 1
    assert stats["stream_fallback_count"] == 1
    assert stats["recovered_count"] == 1
    assert stats["failed_count"] == 1
    assert "429" in stats["last_error"]
    assert snapshot["recent_events"]

    reset_snapshot = await monitor.reset()
    reset_stats = reset_snapshot["stats"]
    assert reset_stats["llm_retry_count"] == 0
    assert reset_stats["failed_count"] == 0
    assert reset_snapshot["recent_events"] == []

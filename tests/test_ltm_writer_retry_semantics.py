from types import SimpleNamespace

import pytest

from astrbot.core.long_term_memory.policy import MemoryWritePolicy
from astrbot.core.long_term_memory.writer import MemoryWriter


class _FakeMemoryDB:
    def __init__(self, events):
        self._events = list(events)
        self.marked_batches: list[list[str]] = []
        self.retry_batches: list[dict] = []

    async def get_unprocessed_events(self, limit: int = 20):
        return self._events[:limit]

    async def mark_events_processed(self, event_ids: list[str]) -> None:
        self.marked_batches.append(list(event_ids))

    async def mark_events_retry(
        self,
        event_ids: list[str],
        *,
        error: str,
        max_attempts: int = 5,
        base_delay_seconds: int = 30,
        max_delay_seconds: int = 3600,
    ) -> tuple[int, int]:
        self.retry_batches.append(
            {
                "event_ids": list(event_ids),
                "error": error,
                "max_attempts": max_attempts,
                "base_delay_seconds": base_delay_seconds,
                "max_delay_seconds": max_delay_seconds,
            }
        )
        return (len(event_ids), 0)


def _event(event_id: str, scope_id: str = "scope-1"):
    return SimpleNamespace(
        event_id=event_id,
        scope="user",
        scope_id=scope_id,
        source_role="user",
        content={"text": "hello"},
    )


@pytest.mark.asyncio
async def test_writer_keeps_events_pending_when_extraction_raises(monkeypatch):
    db = _FakeMemoryDB([_event("e1")])
    writer = MemoryWriter(db)

    async def _raise_extract(*args, **kwargs):
        raise RuntimeError("extract failed")

    monkeypatch.setattr(
        "astrbot.core.long_term_memory.writer.extract_candidates",
        _raise_extract,
    )

    count = await writer.process_pending_events(
        provider=object(),  # not used by monkeypatched extractor
        write_policy=MemoryWritePolicy(enable=True),
    )

    assert count == 0
    assert db.marked_batches == []
    assert len(db.retry_batches) == 1
    assert db.retry_batches[0]["event_ids"] == ["e1"]
    assert "extract" in db.retry_batches[0]["error"]


@pytest.mark.asyncio
async def test_writer_keeps_events_pending_when_candidate_pipeline_errors(monkeypatch):
    db = _FakeMemoryDB([_event("e1")])
    writer = MemoryWriter(db)

    async def _ok_extract(*args, **kwargs):
        return [{"type": "profile", "fact": "x", "fact_key": "k"}]

    async def _raise_process(*args, **kwargs):
        raise RuntimeError("pipeline error")

    monkeypatch.setattr(
        "astrbot.core.long_term_memory.writer.extract_candidates",
        _ok_extract,
    )
    monkeypatch.setattr(writer, "_process_candidate", _raise_process)

    count = await writer.process_pending_events(
        provider=object(),
        write_policy=MemoryWritePolicy(enable=True),
    )

    assert count == 0
    assert db.marked_batches == []
    assert len(db.retry_batches) == 1
    assert db.retry_batches[0]["event_ids"] == ["e1"]
    assert "pipeline" in db.retry_batches[0]["error"]


@pytest.mark.asyncio
async def test_writer_marks_events_processed_when_no_runtime_errors(monkeypatch):
    db = _FakeMemoryDB([_event("e1")])
    writer = MemoryWriter(db)

    async def _empty_extract(*args, **kwargs):
        return []

    monkeypatch.setattr(
        "astrbot.core.long_term_memory.writer.extract_candidates",
        _empty_extract,
    )

    count = await writer.process_pending_events(
        provider=object(),
        write_policy=MemoryWritePolicy(enable=True),
    )

    assert count == 0
    assert db.marked_batches == [["e1"]]
    assert db.retry_batches == []


@pytest.mark.asyncio
async def test_writer_passes_scope_id_as_extractor_session_id(monkeypatch):
    scope_id = "qq:FriendMessage:1025332440"
    db = _FakeMemoryDB([_event("e1", scope_id=scope_id)])
    writer = MemoryWriter(db)
    capture: dict = {}

    async def _capture_extract(*args, **kwargs):
        capture["session_id"] = kwargs.get("session_id")
        return []

    monkeypatch.setattr(
        "astrbot.core.long_term_memory.writer.extract_candidates",
        _capture_extract,
    )

    await writer.process_pending_events(
        provider=object(),
        write_policy=MemoryWritePolicy(enable=True),
    )

    assert capture.get("session_id") == scope_id

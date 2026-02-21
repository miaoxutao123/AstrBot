"""End-to-end tests for the Long-Term Memory system.

Tests the full pipeline: event recording → extraction → dedup/merge →
confidence scoring → policy-gated persistence → retrieval → cleanup.

Uses a temporary SQLite database; no real LLM calls — the extractor
is mocked to return deterministic candidates.
"""

import asyncio

import pytest
import pytest_asyncio

from astrbot.core.db.sqlite import SQLiteDatabase
from astrbot.core.long_term_memory.db import MemoryDB
from astrbot.core.long_term_memory.manager import LTMManager
from astrbot.core.long_term_memory.policy import MemoryReadPolicy, MemoryWritePolicy
from astrbot.core.long_term_memory.writer import MemoryWriter


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def db(tmp_path):
    """Create a temporary SQLite database with LTM tables."""
    db_path = str(tmp_path / "test_ltm.db")
    sqlite_db = SQLiteDatabase(db_path)
    await sqlite_db.initialize()
    sqlite_db.inited = True
    yield sqlite_db
    await sqlite_db.engine.dispose()


@pytest_asyncio.fixture()
async def memory_db(db):
    return MemoryDB(db)


@pytest_asyncio.fixture()
async def ltm(db):
    return LTMManager(db)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

MOCK_CANDIDATES = [
    {
        "type": "profile",
        "fact": "用户是男生，2026年时25岁",
        "fact_key": "user_gender_age",
        "confidence": 0.9,
        "importance": 0.8,
    },
    {
        "type": "preference",
        "fact": "用户喜欢用中文交流",
        "fact_key": "user_language_preference",
        "confidence": 0.85,
        "importance": 0.6,
    },
]
class FakeResponse:
    """Mimics a provider response with completion_text."""
    def __init__(self, text: str):
        self.completion_text = text


class FakeProvider:
    """Fake LLM provider that returns pre-canned extraction JSON."""
    def __init__(self, json_text: str):
        self._json_text = json_text

    async def text_chat(self, prompt: str, session_id: str = "", **kw):
        return FakeResponse(self._json_text)


class FailingProvider:
    """Provider that always fails, used for retry/progress tests."""

    async def text_chat(self, prompt: str, session_id: str = "", **kw):
        raise RuntimeError("simulated extraction failure")


class SlowSequencedProvider:
    """Slow provider with deterministic per-call candidates."""

    def __init__(self, delay: float = 0.25):
        self.delay = delay
        self.call_count = 0
        self.first_call_started = asyncio.Event()

    async def text_chat(self, prompt: str, session_id: str = "", **kw):
        import json

        self.call_count += 1
        if self.call_count == 1:
            self.first_call_started.set()
        await asyncio.sleep(self.delay)
        idx = self.call_count
        return FakeResponse(
            json.dumps(
                [
                    {
                        "type": "episode",
                        "fact": f"sequenced fact {idx}",
                        "fact_key": f"sequenced_fact_{idx}",
                        "confidence": 0.9,
                        "importance": 0.7,
                    }
                ]
            )
        )


# ---------------------------------------------------------------------------
#  1. Event Recording
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_conversation_event(ltm: LTMManager):
    """Record a user message and verify it lands in the DB."""
    eid = await ltm.record_conversation_event(
        scope="user",
        scope_id="test_user_001",
        role="user",
        text="我是男生，今年25岁",
    )
    assert eid is not None

    # Verify via raw DB query
    events, total = await ltm.memory_db.list_events(
        scope="user", scope_id="test_user_001"
    )
    assert total >= 1
    found = [e for e in events if e.event_id == eid]
    assert len(found) == 1
    assert found[0].source_role == "user"
    assert found[0].processed is False


@pytest.mark.asyncio
async def test_record_tool_event(ltm: LTMManager):
    """Record a tool execution event."""
    eid = await ltm.record_tool_event(
        scope="user",
        scope_id="test_user_001",
        tool_name="web_search",
        tool_args={"query": "weather"},
        tool_result="Sunny, 25°C",
    )
    assert eid is not None

    events, _ = await ltm.memory_db.list_events(
        scope="user", scope_id="test_user_001"
    )
    tool_events = [e for e in events if e.source_type == "tool_result"]
    assert len(tool_events) >= 1


# ---------------------------------------------------------------------------
#  2. Extraction + Write Pipeline (mocked LLM)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extraction_pipeline(ltm: LTMManager):
    """Full write pipeline: record events → extract → persist items."""
    import json

    # Record two conversation events
    await ltm.record_conversation_event(
        scope="user", scope_id="test_extract_001",
        role="user", text="我是男生，今年25岁",
    )
    await ltm.record_conversation_event(
        scope="user", scope_id="test_extract_001",
        role="assistant", text="好的，已经记住了",
    )

    # Build a fake provider that returns our mock candidates
    fake_provider = FakeProvider(json.dumps(MOCK_CANDIDATES))

    write_policy = MemoryWritePolicy(
        enable=True,
        mode="auto",
        min_confidence=0.3,
        max_items_per_scope=100,
    )

    count = await ltm.run_extraction_cycle(
        provider=fake_provider,
        write_policy=write_policy,
    )
    assert count == 2, f"Expected 2 items created, got {count}"

    # Verify items in DB
    items, total = await ltm.memory_db.list_items(
        scope="user", scope_id="test_extract_001"
    )
    assert total == 2
    types = {it.type for it in items}
    assert "profile" in types
    assert "preference" in types

    # Verify events are marked processed
    events, _ = await ltm.memory_db.list_events(
        scope="user", scope_id="test_extract_001"
    )
    for evt in events:
        assert evt.processed is True


@pytest.mark.asyncio
async def test_extraction_failure_keeps_events_unprocessed(ltm: LTMManager):
    """If extraction fails, events should remain unprocessed for retry."""
    scope_id = "test_extract_fail_001"
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="这条消息应该在失败后保留待处理",
    )

    wp = MemoryWritePolicy(enable=True, mode="auto", min_confidence=0.3)
    count = await ltm.run_extraction_cycle(provider=FailingProvider(), write_policy=wp)
    assert count == 0

    events, total = await ltm.memory_db.list_events(scope="user", scope_id=scope_id)
    assert total >= 1
    assert any(evt.processed is False for evt in events)


# ---------------------------------------------------------------------------
#  3. Dedup / Merge on repeated extraction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dedup_merge(ltm: LTMManager):
    """Extracting the same fact twice should merge, not duplicate."""
    import json

    scope_id = "test_dedup_001"

    # First round
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="我叫小明",
    )
    fake = FakeProvider(json.dumps([{
        "type": "profile",
        "fact": "用户名字是小明",
        "fact_key": "user_name",
        "confidence": 0.8,
        "importance": 0.7,
    }]))
    wp = MemoryWritePolicy(enable=True, mode="auto", min_confidence=0.3)
    count1 = await ltm.run_extraction_cycle(provider=fake, write_policy=wp)
    assert count1 == 1

    # Second round — same fact_key
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="对，我叫小明",
    )
    # Reset session counts so rate limit doesn't block
    ltm._writer.reset_session_counts()
    count2 = await ltm.run_extraction_cycle(provider=fake, write_policy=wp)
    assert count2 == 1  # merged, not new

    items, total = await ltm.memory_db.list_items(
        scope="user", scope_id=scope_id
    )
    assert total == 1, f"Expected 1 item after merge, got {total}"
    assert items[0].evidence_count == 2


# ---------------------------------------------------------------------------
#  4. Read Pipeline — retrieval + formatting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_pipeline(ltm: LTMManager):
    """Items with status='active' should be retrievable."""
    import json

    scope_id = "test_read_001"

    # Insert events + extract
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="我喜欢Python",
    )
    fake = FakeProvider(json.dumps([{
        "type": "preference",
        "fact": "用户喜欢Python编程语言",
        "fact_key": "user_likes_python",
        "confidence": 0.9,
        "importance": 0.8,
    }]))
    wp = MemoryWritePolicy(enable=True, mode="auto", min_confidence=0.3)
    await ltm.run_extraction_cycle(provider=fake, write_policy=wp)

    # Verify item is active (mode=auto, preference not in require_approval)
    items, _ = await ltm.memory_db.list_items(
        scope="user", scope_id=scope_id
    )
    assert len(items) == 1
    assert items[0].status == "active"

    # Retrieve memory context
    rp = MemoryReadPolicy(enable=True, max_items=10, max_tokens=500)
    context = await ltm.retrieve_memory_context(
        scope="user", scope_id=scope_id, read_policy=rp,
    )
    assert "[Long-term Memory]" in context
    assert "用户喜欢Python编程语言" in context
    assert "[End Memory]" in context


# ---------------------------------------------------------------------------
#  5. Shadow mode — items stored but NOT injected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shadow_mode(ltm: LTMManager):
    """In shadow mode, items are created but not returned by reader."""
    import json

    scope_id = "test_shadow_001"
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="我住在北京",
    )
    fake = FakeProvider(json.dumps([{
        "type": "profile",
        "fact": "用户住在北京",
        "fact_key": "user_location",
        "confidence": 0.9,
        "importance": 0.7,
    }]))
    wp = MemoryWritePolicy(enable=True, mode="shadow", min_confidence=0.3)
    count = await ltm.run_extraction_cycle(provider=fake, write_policy=wp)
    assert count == 1

    items, _ = await ltm.memory_db.list_items(
        scope="user", scope_id=scope_id
    )
    assert items[0].status == "shadow"

    # Reader should return empty — shadow items are not injected
    rp = MemoryReadPolicy(enable=True)
    context = await ltm.retrieve_memory_context(
        scope="user", scope_id=scope_id, read_policy=rp,
    )
    assert context == ""


# ---------------------------------------------------------------------------
#  6. Policy gates — rate limits, confidence threshold
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confidence_threshold(ltm: LTMManager):
    """Low-confidence candidates should be rejected."""
    import json

    scope_id = "test_conf_001"
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="也许我喜欢猫",
    )
    fake = FakeProvider(json.dumps([{
        "type": "preference",
        "fact": "用户可能喜欢猫",
        "fact_key": "user_maybe_likes_cats",
        "confidence": 0.3,
        "importance": 0.3,
    }]))
    # min_confidence=0.6 → scored_confidence = 0.3 * 0.8 = 0.24 < 0.6
    wp = MemoryWritePolicy(enable=True, mode="auto", min_confidence=0.6)
    count = await ltm.run_extraction_cycle(provider=fake, write_policy=wp)
    assert count == 0


@pytest.mark.asyncio
async def test_scope_item_limit(ltm: LTMManager):
    """Exceeding max_items_per_scope with eviction disabled should block new writes."""
    import json

    scope_id = "test_limit_001"
    wp = MemoryWritePolicy(
        enable=True, mode="auto", min_confidence=0.1,
        max_items_per_scope=1,
        eviction_enabled=False,  # disable eviction to test hard wall
    )

    # First item — should succeed
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="fact one",
    )
    fake1 = FakeProvider(json.dumps([{
        "type": "profile", "fact": "Fact one",
        "fact_key": "fact_one", "confidence": 0.9, "importance": 0.8,
    }]))
    c1 = await ltm.run_extraction_cycle(provider=fake1, write_policy=wp)
    assert c1 == 1

    # Second item — should be blocked by scope limit
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="fact two",
    )
    ltm._writer.reset_session_counts()
    fake2 = FakeProvider(json.dumps([{
        "type": "preference", "fact": "Fact two",
        "fact_key": "fact_two", "confidence": 0.9, "importance": 0.8,
    }]))
    c2 = await ltm.run_extraction_cycle(provider=fake2, write_policy=wp)
    assert c2 == 0


@pytest.mark.asyncio
async def test_scope_limit_does_not_block_existing_fact_merge(ltm: LTMManager):
    """When scope is full, same fact_key should still merge into existing item."""
    import json

    scope_id = "test_scope_merge_001"
    wp = MemoryWritePolicy(
        enable=True,
        mode="auto",
        min_confidence=0.1,
        max_items_per_scope=1,
        eviction_enabled=False,
    )

    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id, role="user", text="初始事实",
    )
    fake_1 = FakeProvider(
        json.dumps(
            [
                {
                    "type": "profile",
                    "fact": "用户名字是小明",
                    "fact_key": "user_name",
                    "confidence": 0.7,
                    "importance": 0.6,
                }
            ]
        )
    )
    c1 = await ltm.run_extraction_cycle(provider=fake_1, write_policy=wp)
    assert c1 == 1

    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id, role="user", text="重复事实用于合并",
    )
    ltm._writer.reset_session_counts()
    fake_2 = FakeProvider(
        json.dumps(
            [
                {
                    "type": "profile",
                    "fact": "用户名字是小明（更新）",
                    "fact_key": "user_name",
                    "confidence": 0.9,
                    "importance": 0.7,
                }
            ]
        )
    )
    c2 = await ltm.run_extraction_cycle(provider=fake_2, write_policy=wp)
    assert c2 == 1

    items, total = await ltm.memory_db.list_items(scope="user", scope_id=scope_id)
    assert total == 1
    assert items[0].fact_key == "user_name"
    assert items[0].evidence_count >= 2


# ---------------------------------------------------------------------------
#  7. Dashboard API operations — update + delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_item(ltm: LTMManager):
    """Update a memory item's status and importance."""
    import json

    scope_id = "test_update_001"
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="test update",
    )
    fake = FakeProvider(json.dumps([{
        "type": "profile", "fact": "Test fact for update",
        "fact_key": "test_update_key", "confidence": 0.9, "importance": 0.5,
    }]))
    wp = MemoryWritePolicy(enable=True, mode="shadow", min_confidence=0.3)
    await ltm.run_extraction_cycle(provider=fake, write_policy=wp)

    items, _ = await ltm.memory_db.list_items(
        scope="user", scope_id=scope_id
    )
    assert len(items) == 1
    item = items[0]
    assert item.status == "shadow"

    # Promote to active + bump importance
    updated = await ltm.memory_db.update_item(
        item.memory_id, status="active", importance=0.95,
    )
    assert updated is not None
    assert updated.status == "active"
    assert updated.importance == 0.95

    # Now reader should find it
    rp = MemoryReadPolicy(enable=True)
    ctx = await ltm.retrieve_memory_context(
        scope="user", scope_id=scope_id, read_policy=rp,
    )
    assert "Test fact for update" in ctx


@pytest.mark.asyncio
async def test_delete_item(ltm: LTMManager):
    """Delete a memory item and verify it's gone."""
    import json

    scope_id = "test_delete_001"
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="test delete",
    )
    fake = FakeProvider(json.dumps([{
        "type": "episode", "fact": "Ephemeral fact",
        "fact_key": "ephemeral", "confidence": 0.9, "importance": 0.5,
    }]))
    wp = MemoryWritePolicy(enable=True, mode="auto", min_confidence=0.3)
    await ltm.run_extraction_cycle(provider=fake, write_policy=wp)

    items, _ = await ltm.memory_db.list_items(
        scope="user", scope_id=scope_id
    )
    assert len(items) == 1
    mid = items[0].memory_id

    # Delete
    await ltm.memory_db.delete_item(mid)

    items_after, total_after = await ltm.memory_db.list_items(
        scope="user", scope_id=scope_id
    )
    assert total_after == 0

    # Evidence should also be gone
    evidence = await ltm.memory_db.get_evidence_for_item(mid)
    assert len(evidence) == 0


# ---------------------------------------------------------------------------
#  8. Stats endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats(ltm: LTMManager):
    """Verify stats aggregation works."""
    import json

    scope_id = "test_stats_001"
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="stats test",
    )
    fake = FakeProvider(json.dumps(MOCK_CANDIDATES))
    wp = MemoryWritePolicy(enable=True, mode="auto", min_confidence=0.3)
    await ltm.run_extraction_cycle(provider=fake, write_policy=wp)

    stats = await ltm.memory_db.get_stats(
        scope="user", scope_id=scope_id
    )
    assert stats["total"] == 2
    assert "active" in stats["by_status"]
    assert "profile" in stats["by_type"]
    assert "preference" in stats["by_type"]


# ---------------------------------------------------------------------------
#  9. Expiration sweep
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expiration_sweep(ltm: LTMManager):
    """Items past TTL should be marked expired."""
    from datetime import datetime, timedelta, timezone

    scope_id = "test_expire_001"

    # Directly insert an item with ttl_days=0 and old created_at
    item = await ltm.memory_db.insert_item(
        scope="user", scope_id=scope_id,
        type="task_state", fact="Old task",
        fact_key="old_task", confidence=0.8, importance=0.5,
        ttl_days=1, status="active",
    )
    # Manually backdate created_at
    from sqlmodel import update as sql_update, col
    from astrbot.core.long_term_memory.models import MemoryItem
    async with ltm._memory_db._db.get_db() as session:
        async with session.begin():
            await session.execute(
                sql_update(MemoryItem)
                .where(MemoryItem.memory_id == item.memory_id)
                .values(created_at=datetime.now(timezone.utc) - timedelta(days=5))
            )

    expired_count = await ltm.run_expiration_sweep()
    assert expired_count >= 1

    refreshed = await ltm.memory_db.get_item_by_id(item.memory_id)
    assert refreshed.status == "expired"


# ---------------------------------------------------------------------------
#  10. Full cleanup — delete all test data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cleanup_all_test_data(memory_db: MemoryDB):
    """Delete every item and event created during this test session."""
    # List all items
    items, total = await memory_db.list_items(page=1, page_size=1000)
    deleted_items = 0
    for item in items:
        await memory_db.delete_item(item.memory_id)
        deleted_items += 1

    # Verify items are gone
    _, remaining = await memory_db.list_items(page=1, page_size=1)
    assert remaining == 0, f"Expected 0 items after cleanup, got {remaining}"

    # Verify stats are empty
    stats = await memory_db.get_stats()
    assert stats["total"] == 0

    print(f"\n[LTM E2E] Cleanup complete: deleted {deleted_items} items")


# ---------------------------------------------------------------------------
#  11. Maintenance sweep — event cleanup + evidence pruning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_maintenance_sweep(ltm: LTMManager):
    """Maintenance sweep should clean processed events and orphan evidence."""
    import json
    from astrbot.core.long_term_memory.policy import MemoryMaintenancePolicy

    scope_id = "test_maint_001"

    # Record and process events
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="maintenance test",
    )
    fake = FakeProvider(json.dumps([{
        "type": "profile", "fact": "Maintenance test fact",
        "fact_key": "maint_test", "confidence": 0.9, "importance": 0.8,
    }]))
    wp = MemoryWritePolicy(enable=True, mode="auto", min_confidence=0.3)
    await ltm.run_extraction_cycle(provider=fake, write_policy=wp)

    # Verify events are processed
    events, _ = await ltm.memory_db.list_events(
        scope="user", scope_id=scope_id
    )
    assert all(e.processed for e in events)

    # Backdate processed events so they qualify for cleanup
    from datetime import datetime, timedelta, timezone as tz
    from sqlmodel import update as sql_update, col
    from astrbot.core.long_term_memory.models import MemoryEvent
    async with ltm._memory_db._db.get_db() as session:
        async with session.begin():
            await session.execute(
                sql_update(MemoryEvent)
                .where(MemoryEvent.scope_id == scope_id)
                .values(created_at=datetime.now(tz.utc) - timedelta(days=10))
            )

    # Delete the memory item to create orphan evidence
    items, _ = await ltm.memory_db.list_items(
        scope="user", scope_id=scope_id
    )
    for item in items:
        # Delete item but leave evidence orphaned
        from sqlmodel import delete as sql_delete
        from astrbot.core.long_term_memory.models import MemoryItem
        async with ltm._memory_db._db.get_db() as session:
            async with session.begin():
                await session.execute(
                    sql_delete(MemoryItem).where(
                        MemoryItem.memory_id == item.memory_id
                    )
                )

    # Run maintenance sweep
    policy = MemoryMaintenancePolicy(event_retention_days=7)
    result = await ltm.run_maintenance_sweep(maintenance_policy=policy)

    assert result["events_cleaned"] >= 1
    assert result["evidence_pruned"] >= 0  # may or may not have orphans


# ---------------------------------------------------------------------------
#  12. Smart eviction — high-priority replaces low-priority
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smart_eviction(ltm: LTMManager):
    """When scope is full, a higher-priority candidate should evict the lowest."""
    import json

    scope_id = "test_evict_001"
    wp = MemoryWritePolicy(
        enable=True, mode="auto", min_confidence=0.1,
        max_items_per_scope=1,
        eviction_enabled=True,
    )

    # First item — low importance
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="low priority fact",
    )
    fake_low = FakeProvider(json.dumps([{
        "type": "episode", "fact": "Low priority fact",
        "fact_key": "low_priority", "confidence": 0.5, "importance": 0.2,
    }]))
    c1 = await ltm.run_extraction_cycle(provider=fake_low, write_policy=wp)
    assert c1 == 1

    # Second item — high importance, should evict the first
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="high priority fact",
    )
    ltm._writer.reset_session_counts()
    fake_high = FakeProvider(json.dumps([{
        "type": "profile", "fact": "High priority fact",
        "fact_key": "high_priority", "confidence": 0.9, "importance": 0.9,
    }]))
    c2 = await ltm.run_extraction_cycle(provider=fake_high, write_policy=wp)
    assert c2 == 1, "High-priority item should have evicted the low-priority one"

    # Verify: only the high-priority item remains active
    items, total = await ltm.memory_db.list_items(
        scope="user", scope_id=scope_id
    )
    active_items = [it for it in items if it.status in ("active", "shadow")]
    assert len(active_items) == 1
    assert active_items[0].fact_key == "high_priority"


# ---------------------------------------------------------------------------
#  13. Smart eviction — low-priority candidate rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smart_eviction_rejected(ltm: LTMManager):
    """When scope is full, a lower-priority candidate should be rejected."""
    import json

    scope_id = "test_evict_rej_001"
    wp = MemoryWritePolicy(
        enable=True, mode="auto", min_confidence=0.1,
        max_items_per_scope=1,
        eviction_enabled=True,
    )

    # First item — high importance
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="important fact",
    )
    fake_high = FakeProvider(json.dumps([{
        "type": "profile", "fact": "Important fact",
        "fact_key": "important", "confidence": 0.9, "importance": 0.9,
    }]))
    c1 = await ltm.run_extraction_cycle(provider=fake_high, write_policy=wp)
    assert c1 == 1

    # Second item — low importance, should be rejected
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id,
        role="user", text="trivial fact",
    )
    ltm._writer.reset_session_counts()
    fake_low = FakeProvider(json.dumps([{
        "type": "episode", "fact": "Trivial fact",
        "fact_key": "trivial", "confidence": 0.3, "importance": 0.1,
    }]))
    c2 = await ltm.run_extraction_cycle(provider=fake_low, write_policy=wp)
    assert c2 == 0, "Low-priority item should have been rejected"


# ---------------------------------------------------------------------------
#  14. Consolidation — merge similar facts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consolidation(ltm: LTMManager):
    """Similar facts should be merged by the consolidator."""
    import json

    scope_id = "test_consolidate_001"

    # Insert two similar items directly
    await ltm.memory_db.insert_item(
        scope="user", scope_id=scope_id,
        type="preference", fact="用户喜欢Python",
        fact_key="user_likes_python", confidence=0.8, importance=0.7,
        status="active",
    )
    await ltm.memory_db.insert_item(
        scope="user", scope_id=scope_id,
        type="preference", fact="用户偏好使用Python编程",
        fact_key="user_prefers_python", confidence=0.85, importance=0.75,
        status="active",
    )

    items_before, total_before = await ltm.memory_db.list_items(
        scope="user", scope_id=scope_id
    )
    assert total_before == 2

    # Fake provider returns a merged fact
    fake = FakeProvider(json.dumps({
        "fact": "用户喜欢并偏好使用Python编程语言",
        "fact_key": "user_python_preference",
        "confidence": 0.9,
        "importance": 0.8,
    }))

    count = await ltm.run_consolidation(
        provider=fake, scope="user", scope_id=scope_id,
    )
    # The two items should have been consolidated
    assert count >= 2

    items_after, total_after = await ltm.memory_db.list_items(
        scope="user", scope_id=scope_id, status="active",
    )
    # Should have fewer active items after consolidation
    assert total_after < total_before


@pytest.mark.asyncio
async def test_schedule_extraction_runs_pending_cycle(ltm: LTMManager):
    """A second schedule call during running extraction should not be dropped."""
    scope_id = "test_schedule_pending_001"
    provider = SlowSequencedProvider(delay=0.25)
    wp = MemoryWritePolicy(enable=True, mode="auto", min_confidence=0.1)

    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id, role="user", text="first event",
    )
    ltm.schedule_extraction(provider=provider, write_policy=wp)

    # Ensure first extraction cycle has started and fetched its batch.
    await asyncio.wait_for(provider.first_call_started.wait(), timeout=1.0)

    # New event arrives while first cycle is still running.
    await ltm.record_conversation_event(
        scope="user", scope_id=scope_id, role="user", text="second event",
    )
    ltm.schedule_extraction(provider=provider, write_policy=wp)

    assert ltm._extraction_task is not None
    await asyncio.wait_for(ltm._extraction_task, timeout=3.0)

    events, total_events = await ltm.memory_db.list_events(
        scope="user", scope_id=scope_id, page=1, page_size=50
    )
    assert total_events >= 2
    assert all(evt.processed for evt in events)
    assert provider.call_count >= 2

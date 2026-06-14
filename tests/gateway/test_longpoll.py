"""Tests for LongPoll queue."""

import pytest
import asyncio
from astrbot.core.gateway.longpoll import LongPollQueue
from astrbot.core.gateway.envelope import MessageEnvelope, EventType, PlatformInfo, SessionInfo, SenderInfo, MessagePayload


def _make_envelope(text="hi"):
    return MessageEnvelope.new(
        event_type=EventType.MESSAGE_RECEIVE,
        platform=PlatformInfo(id="tg_1", name="telegram", type="telegram"),
        session=SessionInfo(umo="telegram:FriendMessage:123", session_id="123", message_type="FriendMessage"),
        sender=SenderInfo(id="123", name="Alice"),
        message=MessagePayload(text=text, chain=[]),
    )


class TestLongPollQueue:
    @pytest.mark.asyncio
    async def test_enqueue_dequeue(self):
        lp = LongPollQueue({"enabled": True, "max_queue_size": 100})
        env = _make_envelope()
        await lp.enqueue(env)
        events = await lp.dequeue("key_1", timeout=1.0)
        assert len(events) == 1
        assert events[0]["message"]["text"] == "hi"

    @pytest.mark.asyncio
    async def test_empty_timeout(self):
        lp = LongPollQueue({"enabled": True})
        events = await lp.dequeue("key_1", timeout=0.1)
        assert events == []

    @pytest.mark.asyncio
    async def test_ack(self):
        lp = LongPollQueue({"enabled": True})
        lp._unacked["evt_abc"] = {"key": "key_1"}
        lp.ack("key_1", ["evt_abc"])
        assert "evt_abc" not in lp._unacked

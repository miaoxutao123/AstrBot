"""Tests for Webhook pusher."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from astrbot.core.gateway.webhook import WebhookPusher, WebhookEndpoint
from astrbot.core.gateway.envelope import MessageEnvelope, EventType, PlatformInfo, SessionInfo, SenderInfo, MessagePayload


def _make_envelope():
    return MessageEnvelope.new(
        event_type=EventType.MESSAGE_RECEIVE,
        platform=PlatformInfo(id="tg_1", name="telegram", type="telegram"),
        session=SessionInfo(umo="telegram:FriendMessage:123", session_id="123", message_type="FriendMessage"),
        sender=SenderInfo(id="123", name="Alice"),
        message=MessagePayload(text="hi", chain=[]),
    )


class TestWebhookPusher:
    @pytest.mark.asyncio
    async def test_filter_platform(self):
        ep = WebhookEndpoint(name="test", url="http://localhost", secret="s", timeout=5, filter_cfg={"platforms": ["discord"]})
        assert not ep.accepts("telegram")
        assert ep.accepts("discord")

    @pytest.mark.asyncio
    async def test_no_filter_accepts_all(self):
        ep = WebhookEndpoint(name="test", url="http://localhost", secret="s", timeout=5, filter_cfg={})
        assert ep.accepts("telegram")
        assert ep.accepts("discord")

    @pytest.mark.asyncio
    async def test_push_disabled(self):
        pusher = WebhookPusher({"enabled": False})
        await pusher.initialize()
        env = _make_envelope()
        await pusher.push(env)  # should not raise

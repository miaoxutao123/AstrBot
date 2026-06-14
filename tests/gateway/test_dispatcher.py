"""Tests for GatewayDispatcher."""

import pytest
from unittest.mock import AsyncMock
from astrbot.core.gateway.dispatcher import GatewayDispatcher
from astrbot.core.gateway.envelope import MessageEnvelope, EventType, PlatformInfo, SessionInfo, SenderInfo, MessagePayload


def _make_envelope():
    return MessageEnvelope.new(
        event_type=EventType.MESSAGE_RECEIVE,
        platform=PlatformInfo(id="tg_1", name="telegram", type="telegram"),
        session=SessionInfo(umo="telegram:FriendMessage:123", session_id="123", message_type="FriendMessage"),
        sender=SenderInfo(id="123", name="Alice"),
        message=MessagePayload(text="hi", chain=[]),
    )


class TestGatewayDispatcher:
    @pytest.mark.asyncio
    async def test_disabled(self):
        disp = GatewayDispatcher({"enabled": False})
        await disp.initialize()
        await disp.dispatch(_make_envelope())  # should not raise

    @pytest.mark.asyncio
    async def test_no_channels(self):
        disp = GatewayDispatcher({"enabled": True, "webhook": {"enabled": False}, "longpoll": {"enabled": False}, "websocket": {"enabled": False}})
        await disp.initialize()
        await disp.dispatch(_make_envelope())  # should not raise

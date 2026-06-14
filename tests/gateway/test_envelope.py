"""Tests for gateway envelope and serializer."""

import pytest
from astrbot.core.gateway.envelope import MessageEnvelope, EventType, PlatformInfo, SessionInfo, SenderInfo, MessagePayload
from astrbot.core.gateway.serializer import MessageSerializer
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.message.components import Plain, At


class TestEnvelope:
    def test_envelope_creation(self):
        env = MessageEnvelope.new(
            event_type=EventType.MESSAGE_RECEIVE,
            platform=PlatformInfo(id="tg_1", name="telegram", type="telegram"),
            session=SessionInfo(umo="telegram:FriendMessage:123", session_id="123", message_type="FriendMessage"),
            sender=SenderInfo(id="123", name="Alice"),
            message=MessagePayload(text="hello", chain=[{"type": "Plain", "text": "hello"}]),
        )
        assert env.type == EventType.MESSAGE_RECEIVE
        assert env.version == "1.0"
        assert env.platform.name == "telegram"
        assert env.event_id.startswith("evt_")

    def test_envelope_to_dict(self):
        env = MessageEnvelope.new(
            event_type=EventType.MESSAGE_RECEIVE,
            platform=PlatformInfo(id="tg_1", name="telegram", type="telegram"),
            session=SessionInfo(umo="telegram:FriendMessage:123", session_id="123", message_type="FriendMessage"),
            sender=SenderInfo(id="123", name="Alice"),
            message=MessagePayload(text="hello", chain=[]),
        )
        d = env.to_dict()
        assert d["type"] == "im.message.receive"
        assert d["platform"]["name"] == "telegram"


class TestSerializer:
    def _make_event(self, text="hi", platform_name="telegram"):
        msg = AstrBotMessage()
        msg.sender = MessageMember(user_id="123", nickname="Alice")
        msg.type = MessageType.FRIEND_MESSAGE
        msg.message_str = text
        msg.message = [Plain(text=text)]
        msg.self_id = "bot_1"
        meta = PlatformMetadata(name=platform_name, id="tg_1", description="")
        return AstrMessageEvent(message_str=text, message_obj=msg, platform_meta=meta, session_id="123")

    def test_serialize_basic(self):
        event = self._make_event("hello world")
        env = MessageSerializer.to_envelope(event)
        assert env.message.text == "hello world"
        assert env.sender.id == "123"
        assert env.sender.name == "Alice"
        assert env.platform.name == "telegram"
        assert env.session.umo == "telegram:FriendMessage:123"

    def test_serialize_chain(self):
        event = self._make_event()
        event.message_obj.message = [Plain(text="hello"), At(qq="456", name="Bob")]
        env = MessageSerializer.to_envelope(event)
        assert len(env.message.chain) == 2
        assert env.message.chain[0]["type"] == "Plain"

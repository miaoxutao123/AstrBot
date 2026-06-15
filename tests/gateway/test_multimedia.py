"""Tests for gateway multimedia serialization and round-trip."""

import pytest
from astrbot.core.gateway.serializer import MessageSerializer
from astrbot.core.gateway.envelope import MessageEnvelope, EventType
from astrbot.core.message.components import Plain, Image, Record, Video, File
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.platform.sources.webchat.message_parts_helper import (
    build_webchat_message_parts,
    parse_webchat_message_parts,
    build_message_chain_from_payload,
)


class TestSerializerMultimedia:
    """Test MessageSerializer for multimedia components."""

    def _make_event(self, chain: list, text: str = "") -> AstrMessageEvent:
        msg = AstrBotMessage()
        msg.sender = MessageMember(user_id="123", nickname="Alice")
        msg.type = MessageType.FRIEND_MESSAGE
        msg.message_str = text
        msg.message = chain
        msg.self_id = "bot_1"
        meta = PlatformMetadata(name="telegram", id="tg_1", description="")
        return AstrMessageEvent(message_str=text, message_obj=msg, platform_meta=meta, session_id="123")

    @pytest.mark.asyncio
    async def test_serialize_image_with_url(self):
        event = self._make_event([Image.fromURL("https://example.com/img.png")])
        env = await MessageSerializer.to_envelope(event)
        assert env.message.chain[0]["type"] == "Image"
        assert env.message.chain[0]["data"]["file"] == "https://example.com/img.png"

    @pytest.mark.asyncio
    async def test_serialize_image_with_local_path_fallback(self):
        """When file_token_service is not configured, Image with local path falls back to raw file."""
        img = Image.fromFileSystem("/tmp/test.jpg")
        event = self._make_event([img])
        env = await MessageSerializer.to_envelope(event)
        assert env.message.chain[0]["type"] == "Image"
        # register_to_file_service fails -> fallback to file field
        assert "file" in env.message.chain[0]["data"]
        assert env.message.chain[0]["data"]["file"].startswith("file://")

    @pytest.mark.asyncio
    async def test_serialize_record_with_url(self):
        event = self._make_event([Record.fromURL("https://example.com/voice.mp3")])
        env = await MessageSerializer.to_envelope(event)
        assert env.message.chain[0]["type"] == "Record"
        assert env.message.chain[0]["data"]["file"] == "https://example.com/voice.mp3"

    @pytest.mark.asyncio
    async def test_serialize_video_with_url(self):
        event = self._make_event([Video.fromURL("https://example.com/video.mp4")])
        env = await MessageSerializer.to_envelope(event)
        assert env.message.chain[0]["type"] == "Video"
        assert env.message.chain[0]["data"]["file"] == "https://example.com/video.mp4"

    @pytest.mark.asyncio
    async def test_serialize_file_with_url(self):
        event = self._make_event([File(name="report.pdf", url="https://example.com/report.pdf")])
        env = await MessageSerializer.to_envelope(event)
        assert env.message.chain[0]["type"] == "File"
        assert env.message.chain[0]["data"]["file"] == "https://example.com/report.pdf"
        assert env.message.chain[0]["data"]["name"] == "report.pdf"

    @pytest.mark.asyncio
    async def test_serialize_plain(self):
        event = self._make_event([Plain(text="hello")], text="hello")
        env = await MessageSerializer.to_envelope(event)
        assert env.message.chain[0]["type"] == "text"
        assert env.message.chain[0]["data"]["text"] == "hello"

    @pytest.mark.asyncio
    async def test_serialize_mixed_chain(self):
        event = self._make_event(
            [Plain(text="look at this"), Image.fromURL("https://example.com/img.png")],
            text="look at this",
        )
        env = await MessageSerializer.to_envelope(event)
        assert len(env.message.chain) == 2
        assert env.message.chain[0]["type"] == "text"
        assert env.message.chain[1]["type"] == "Image"
        assert env.message.chain[1]["data"]["file"] == "https://example.com/img.png"

    @pytest.mark.asyncio
    async def test_serialize_no_internal_fields_exposed(self):
        """Internal fields like 'path' should not appear in the final output when a URL is available."""
        event = self._make_event([Image.fromURL("https://example.com/img.png")])
        env = await MessageSerializer.to_envelope(event)
        data = env.message.chain[0]["data"]
        assert "path" not in data
        assert "_type" not in data


class TestMessagePartsHelperUrl:
    """Test build/parse message parts with direct URL support."""

    @pytest.mark.asyncio
    async def test_build_webchat_image_url(self):
        parts = await build_webchat_message_parts(
            [{"type": "image", "url": "https://example.com/img.png"}],
            get_attachment_by_id=None,
            strict=True,
        )
        assert len(parts) == 1
        assert parts[0]["type"] == "image"
        assert parts[0]["url"] == "https://example.com/img.png"

    @pytest.mark.asyncio
    async def test_build_webchat_record_url(self):
        parts = await build_webchat_message_parts(
            [{"type": "record", "url": "https://example.com/voice.mp3"}],
            get_attachment_by_id=None,
            strict=True,
        )
        assert len(parts) == 1
        assert parts[0]["type"] == "record"
        assert parts[0]["url"] == "https://example.com/voice.mp3"

    @pytest.mark.asyncio
    async def test_build_webchat_video_url(self):
        parts = await build_webchat_message_parts(
            [{"type": "video", "url": "https://example.com/video.mp4"}],
            get_attachment_by_id=None,
            strict=True,
        )
        assert len(parts) == 1
        assert parts[0]["type"] == "video"
        assert parts[0]["url"] == "https://example.com/video.mp4"

    @pytest.mark.asyncio
    async def test_build_webchat_file_url(self):
        parts = await build_webchat_message_parts(
            [{"type": "file", "url": "https://example.com/doc.pdf", "filename": "doc.pdf"}],
            get_attachment_by_id=None,
            strict=True,
        )
        assert len(parts) == 1
        assert parts[0]["type"] == "file"
        assert parts[0]["url"] == "https://example.com/doc.pdf"
        assert parts[0]["filename"] == "doc.pdf"

    @pytest.mark.asyncio
    async def test_build_webchat_missing_url_and_attachment_id_raises(self):
        with pytest.raises(ValueError, match="missing attachment_id or url"):
            await build_webchat_message_parts(
                [{"type": "image"}],
                get_attachment_by_id=None,
                strict=True,
            )

    @pytest.mark.asyncio
    async def test_parse_webchat_image_url(self):
        components, text_parts, has_content = await parse_webchat_message_parts(
            [{"type": "image", "url": "https://example.com/img.png"}],
            strict=True,
        )
        assert has_content
        assert len(components) == 1
        assert isinstance(components[0], Image)
        assert components[0].file == "https://example.com/img.png"

    @pytest.mark.asyncio
    async def test_parse_webchat_record_url(self):
        components, _, _ = await parse_webchat_message_parts(
            [{"type": "record", "url": "https://example.com/voice.mp3"}],
            strict=True,
        )
        assert isinstance(components[0], Record)
        assert components[0].file == "https://example.com/voice.mp3"

    @pytest.mark.asyncio
    async def test_parse_webchat_video_url(self):
        components, _, _ = await parse_webchat_message_parts(
            [{"type": "video", "url": "https://example.com/video.mp4"}],
            strict=True,
        )
        assert isinstance(components[0], Video)
        assert components[0].file == "https://example.com/video.mp4"

    @pytest.mark.asyncio
    async def test_parse_webchat_file_url(self):
        components, _, _ = await parse_webchat_message_parts(
            [{"type": "file", "url": "https://example.com/doc.pdf", "filename": "doc.pdf"}],
            strict=True,
        )
        assert isinstance(components[0], File)
        assert components[0].url == "https://example.com/doc.pdf"
        assert components[0].name == "doc.pdf"

    @pytest.mark.asyncio
    async def test_build_message_chain_from_payload_with_url(self):
        chain = await build_message_chain_from_payload(
            [
                {"type": "plain", "text": "hello"},
                {"type": "image", "url": "https://example.com/img.png"},
            ],
            get_attachment_by_id=None,
            strict=True,
        )
        assert len(chain.chain) == 2
        assert isinstance(chain.chain[0], Plain)
        assert isinstance(chain.chain[1], Image)
        assert chain.chain[1].file == "https://example.com/img.png"

    @pytest.mark.asyncio
    async def test_build_message_chain_from_payload_with_attachment_id_raises_when_no_db(self):
        """When get_attachment_by_id is None and attachment_id is used, it should raise clearly."""
        with pytest.raises(ValueError, match="get_attachment_by_id is not provided"):
            await build_message_chain_from_payload(
                [{"type": "image", "attachment_id": "abc123"}],
                get_attachment_by_id=None,
                strict=True,
            )

    @pytest.mark.asyncio
    async def test_build_message_chain_from_payload_plain_only(self):
        chain = await build_message_chain_from_payload(
            [{"type": "plain", "text": "hello"}],
            get_attachment_by_id=None,
            strict=True,
        )
        assert len(chain.chain) == 1
        assert isinstance(chain.chain[0], Plain)

    @pytest.mark.asyncio
    async def test_build_message_chain_from_payload_mixed_url_and_attachment_id(self):
        """URL parts should work even when attachment_id parts are present but DB is None."""
        # This should succeed because only URL parts are used
        chain = await build_message_chain_from_payload(
            [
                {"type": "plain", "text": "hello"},
                {"type": "image", "url": "https://example.com/img.png"},
            ],
            get_attachment_by_id=None,
            strict=True,
        )
        assert len(chain.chain) == 2

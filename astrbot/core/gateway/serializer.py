"""Serialize AstrMessageEvent into MessageEnvelope."""

from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.message.components import BaseMessageComponent, Image, Record, Video, File, Node, Nodes
from astrbot.core import logger
from .envelope import MessageEnvelope, EventType, PlatformInfo, SessionInfo, SenderInfo, MessagePayload


class MessageSerializer:
    """Converts internal AstrMessageEvent to standardized gateway envelope.
    
    For multimedia components (Image, Record, Video, File), the serializer
    attempts to register them with the file_token_service to generate a
    downloadable HTTP URL. If that fails, it falls back to the raw url or file
    field (if it is already an HTTP URL). This ensures external Agents always
    receive a valid URL instead of local paths or base64 blobs.
    """

    @staticmethod
    async def _resolve_media_url(comp: Image | Record | Video | File) -> str | None:
        """Best-effort resolve a media component to a public URL.
        
        Priority:
        1. register_to_file_service() -> http://host/api/file/{token}
        2. comp.url (if it starts with http)
        3. comp.file (if it starts with http)
        4. None (local path / base64 — external Agent cannot access)
        """
        # 1) Try file_token_service (requires callback_api_base)
        try:
            if hasattr(comp, "register_to_file_service"):
                url = await comp.register_to_file_service()
                if url and url.startswith("http"):
                    return url
        except Exception as e:
            logger.debug(f"register_to_file_service failed for {comp.type}: {e}")

        # 2) Fallback to comp.url if it's an HTTP URL
        raw_url = getattr(comp, "url", None)
        if raw_url and str(raw_url).startswith("http"):
            return str(raw_url)

        # 3) Fallback to comp.file if it's an HTTP URL
        raw_file = getattr(comp, "file", None)
        if raw_file and str(raw_file).startswith("http"):
            return str(raw_file)

        return None

    @staticmethod
    async def component_to_dict(comp: BaseMessageComponent) -> dict:
        """Serialize a single message component into a gateway-friendly dict.
        
        For multimedia components, the output is normalized to:
        {"type": "Image", "data": {"file": "http://..."}}
        
        For File components, an additional "name" field is included.
        """
        comp_type = comp.type.name if hasattr(comp.type, "name") else str(comp.type)

        if isinstance(comp, Image | Record | Video):
            url = await MessageSerializer._resolve_media_url(comp)
            data: dict = {}
            if url:
                data["file"] = url
            else:
                # If we cannot produce a URL, preserve the url/file fields
                # so the Agent at least sees the raw reference.
                if getattr(comp, "url", None):
                    data["url"] = comp.url
                if getattr(comp, "file", None):
                    data["file"] = comp.file
                if getattr(comp, "path", None):
                    data["path"] = comp.path
            # Preserve additional fields for Record
            if isinstance(comp, Record) and getattr(comp, "text", None):
                data["text"] = comp.text
            return {"type": comp_type, "data": data}

        if isinstance(comp, File):
            url = await MessageSerializer._resolve_media_url(comp)
            data = {"name": comp.name or ""}
            if url:
                data["file"] = url
            else:
                if comp.url:
                    data["url"] = comp.url
                if comp.file_:
                    data["file"] = comp.file_
                if comp.name:
                    data["name"] = comp.name
            return {"type": comp_type, "data": data}

        if isinstance(comp, Node):
            return await comp.to_dict()

        if isinstance(comp, Nodes):
            return {"type": comp_type, "data": await comp.to_dict()}

        # For all other components, use the existing toDict() method which
        # produces platform-agnostic dicts (e.g. Plain -> {"type": "text", ...})
        try:
            if hasattr(comp, "toDict"):
                return comp.toDict()
        except Exception:
            pass

        # Ultimate fallback: best-effort __dict__ extraction, stripping None
        # and internal fields.
        raw = getattr(comp, "__dict__", {})
        data = {}
        for k, v in raw.items():
            if v is None or k.startswith("_") or k == "type":
                continue
            data[k] = v
        return {"type": comp_type, "data": data}

    @staticmethod
    async def to_envelope(event: AstrMessageEvent) -> MessageEnvelope:
        chain = []
        for comp in event.get_messages():
            chain.append(await MessageSerializer.component_to_dict(comp))

        metadata = {
            "is_at": event.is_at_or_wake_command,
            "is_wake": event.is_wake,
            "is_private": event.is_private_chat(),
            "raw_message_id": getattr(event.message_obj, "message_id", None),
        }

        return MessageEnvelope.new(
            event_type=EventType.MESSAGE_RECEIVE,
            platform=PlatformInfo(
                id=event.get_platform_id(),
                name=event.get_platform_name(),
                type=event.get_platform_name(),
            ),
            session=SessionInfo(
                umo=event.unified_msg_origin,
                session_id=event.session_id,
                message_type=event.get_message_type().name,
                group_id=event.get_group_id(),
            ),
            sender=SenderInfo(
                id=event.get_sender_id(),
                name=event.get_sender_name(),
                role=event.role,
            ),
            message=MessagePayload(
                text=event.get_message_str(),
                chain=chain,
            ),
            metadata=metadata,
        )

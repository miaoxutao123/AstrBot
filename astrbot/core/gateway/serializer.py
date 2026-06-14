"""Serialize AstrMessageEvent into MessageEnvelope."""

from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.message.components import BaseMessageComponent
from .envelope import MessageEnvelope, EventType, PlatformInfo, SessionInfo, SenderInfo, MessagePayload


class MessageSerializer:
    """Converts internal AstrMessageEvent to standardized gateway envelope."""

    @staticmethod
    def component_to_dict(comp: BaseMessageComponent) -> dict:
        """Best-effort serialization of a message component."""
        return {
            "type": comp.type.name if hasattr(comp.type, "name") else str(comp.type),
            "data": getattr(comp, "__dict__", {}),
        }

    @staticmethod
    def to_envelope(event: AstrMessageEvent) -> MessageEnvelope:
        chain = []
        for comp in event.get_messages():
            chain.append(MessageSerializer.component_to_dict(comp))

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

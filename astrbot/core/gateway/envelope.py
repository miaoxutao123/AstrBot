"""MessageEnvelope — standardized outbound event schema for all gateway channels."""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any
from uuid import uuid4
from time import time


class EventType(str, Enum):
    MESSAGE_RECEIVE = "im.message.receive"
    MESSAGE_SEND = "im.message.send"
    PLATFORM_STATUS = "im.platform.status"
    HEARTBEAT = "gateway.heartbeat"


@dataclass
class PlatformInfo:
    id: str
    name: str
    type: str


@dataclass
class SessionInfo:
    umo: str
    session_id: str
    message_type: str
    group_id: str = ""


@dataclass
class SenderInfo:
    id: str
    name: str
    role: str = "member"


@dataclass
class MessagePayload:
    text: str
    chain: list[dict]


@dataclass
class MessageEnvelope:
    event_id: str
    type: EventType
    version: str
    timestamp: float
    platform: PlatformInfo
    session: SessionInfo
    sender: SenderInfo
    message: MessagePayload
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d

    @classmethod
    def new(
        cls,
        event_type: EventType,
        platform: PlatformInfo,
        session: SessionInfo,
        sender: SenderInfo,
        message: MessagePayload,
        metadata: dict | None = None,
    ) -> "MessageEnvelope":
        return cls(
            event_id=f"evt_{uuid4().hex[:16]}",
            type=event_type,
            version="1.0",
            timestamp=time(),
            platform=platform,
            session=session,
            sender=sender,
            message=message,
            metadata=metadata or {},
        )

"""Normalized QQ Official message shared by WebSocket and future webhook."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote


@dataclass(frozen=True, slots=True)
class QQOfficialEndpoint:
    scene: str
    destination_id: str

    def encode(self) -> str:
        return f"{self.scene}:{quote(self.destination_id, safe='')}"

    @classmethod
    def decode(cls, value: str) -> "QQOfficialEndpoint":
        try:
            scene, destination = value.split(":", 1)
        except ValueError as exc:
            raise ValueError("invalid QQ Official endpoint_id") from exc
        if scene not in {"c2c", "group", "channel", "direct"} or not destination:
            raise ValueError("invalid QQ Official endpoint_id")
        return cls(scene, unquote(destination))


@dataclass(frozen=True, slots=True)
class QQOfficialMessage:
    event_type: str
    message_id: str
    endpoint: QQOfficialEndpoint
    conversation_type: str
    sender_id: str
    sender_name: str
    content: str
    attachments: tuple[Mapping[str, Any], ...]
    reply_to: str | None
    timestamp: float
    metadata: Mapping[str, Any]


def normalize_message(
    event_type: str, data: Mapping[str, Any]
) -> QQOfficialMessage | None:
    author = data.get("author")
    if not isinstance(author, Mapping):
        return None
    scene: str
    destination: object
    conversation_type: str
    if event_type == "C2C_MESSAGE_CREATE":
        scene, destination, conversation_type = (
            "c2c",
            author.get("user_openid") or author.get("id"),
            "private",
        )
    elif event_type in {"GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"}:
        scene, destination, conversation_type = (
            "group",
            data.get("group_openid"),
            "group",
        )
    elif event_type == "AT_MESSAGE_CREATE":
        scene, destination, conversation_type = (
            "channel",
            data.get("channel_id"),
            "channel",
        )
    elif event_type == "DIRECT_MESSAGE_CREATE":
        scene, destination, conversation_type = (
            "direct",
            data.get("channel_id") or data.get("guild_id"),
            "private",
        )
    else:
        return None
    message_id = data.get("id")
    sender = (
        author.get("member_openid") or author.get("user_openid") or author.get("id")
    )
    if (
        not isinstance(destination, str)
        or not destination
        or not isinstance(message_id, str)
        or not message_id
        or not isinstance(sender, str)
        or not sender
    ):
        return None
    attachments_value = data.get("attachments")
    attachments = (
        tuple(value for value in attachments_value if isinstance(value, Mapping))
        if isinstance(attachments_value, list)
        else ()
    )
    reference = data.get("message_reference")
    reply_to = (
        reference.get("message_id")
        if isinstance(reference, Mapping)
        and isinstance(reference.get("message_id"), str)
        else None
    )
    timestamp = data.get("timestamp", 0)
    try:
        numeric_timestamp = float(timestamp)
    except (TypeError, ValueError):
        numeric_timestamp = 0.0
    return QQOfficialMessage(
        event_type,
        message_id,
        QQOfficialEndpoint(scene, destination),
        conversation_type,
        sender,
        str(author.get("username") or author.get("member_openid") or sender),
        str(data.get("content") or "").strip(),
        attachments,
        reply_to,
        numeric_timestamp,
        {
            "qq_event_type": event_type,
            "qq_guild_id": data.get("guild_id"),
            "qq_group_openid": data.get("group_openid"),
        },
    )

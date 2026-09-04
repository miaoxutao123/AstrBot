"""Versioned Generic Agent Invoke Protocol models."""

from collections.abc import Mapping, Sequence
from typing import Any

INVOKE_SCHEMA = "astrbot.agent.invoke.v1"
RESULT_SCHEMA = "astrbot.agent.result.v1"


def invoke_for(
    event: Any, session_key: str, external_session_id: str | None, gateway_url: str
) -> dict[str, Any]:
    message = event.message
    if message is None:
        raise ValueError("bridge accepts IM message events only")
    return {
        "schema": INVOKE_SCHEMA,
        "session": {"key": session_key, "external_session_id": external_session_id},
        "input": {
            "type": "im.message",
            "text": message.text,
            "segments": list(message.segments),
            "event": event.raw,
        },
        "context": {
            "current_endpoint": event.source.to_wire(),
            "conversation": message.raw.get("conversation", {}),
            "sender": message.sender,
            "event_id": event.id,
            "message_id": message.id,
            "reply_capability": True,
            "gateway_url": gateway_url,
        },
    }


def parse_result(value: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Validate result.v1, accepting legacy text and canonical text segments."""
    if value.get("schema") != RESULT_SCHEMA:
        raise ValueError("invalid AgentResult schema")
    reply = value.get("reply", {})
    if isinstance(reply, str):
        text = reply
    elif isinstance(reply, Mapping) and isinstance(reply.get("text"), str):
        text = str(reply["text"])
    elif isinstance(reply, Mapping) and isinstance(reply.get("segments"), Sequence):
        text_parts: list[str] = []
        for segment in reply["segments"]:
            if not isinstance(segment, Mapping) or segment.get("type") != "text":
                continue
            data = segment.get("data")
            if isinstance(data, Mapping) and isinstance(data.get("text"), str):
                text_parts.append(str(data["text"]))
        if not text_parts:
            raise ValueError("AgentResult segments require a text segment")
        text = "".join(text_parts)
    else:
        raise ValueError("AgentResult requires reply.text or reply.segments")
    session = value.get("session", {})
    external = (
        session.get("external_session_id") if isinstance(session, Mapping) else None
    )
    external = value.get("external_session_id", external)
    return text, str(external) if external is not None else None

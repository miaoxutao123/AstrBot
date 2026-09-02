"""Versioned Generic Agent Invoke Protocol models."""

from collections.abc import Mapping
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
    """Validate the minimal v1 result and return reply/external session id."""
    if value.get("schema") != RESULT_SCHEMA:
        raise ValueError("invalid AgentResult schema")
    reply = value.get("reply", {})
    if not isinstance(reply, Mapping) or not isinstance(reply.get("text"), str):
        raise ValueError("AgentResult requires reply.text")
    session = value.get("session", {})
    external = (
        session.get("external_session_id") if isinstance(session, Mapping) else None
    )
    return str(reply["text"]), str(external) if external is not None else None

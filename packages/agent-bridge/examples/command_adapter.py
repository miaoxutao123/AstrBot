"""Generic command-mode Agent adapter; a protocol example, not an Agent runtime.

Read one ``astrbot.agent.invoke.v1`` JSON object from stdin and write one
``astrbot.agent.result.v1`` object to stdout. Replace ``call_native_agent``
with an Agent-owned integration without changing Gateway or the Bridge.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any

INVOKE_SCHEMA = "astrbot.agent.invoke.v1"
RESULT_SCHEMA = "astrbot.agent.result.v1"


def call_native_agent(
    *, text: str, segments: list[Mapping[str, Any]], session_id: str | None
) -> tuple[str, str]:
    """Replace with the Agent's own AgentFlow and native session handling."""
    del segments
    return f"echo: {text}", session_id or "example-session"


def handle(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the public invoke envelope and produce a structured result."""
    if request.get("schema") != INVOKE_SCHEMA:
        raise ValueError("expected astrbot.agent.invoke.v1")
    session = request.get("session")
    payload = request.get("input")
    if not isinstance(session, Mapping) or not isinstance(payload, Mapping):
        raise ValueError("invoke requires session and input objects")
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise ValueError("invoke requires canonical input.segments")
    text, session_id = call_native_agent(
        text=str(payload.get("text", "")),
        segments=[item for item in segments if isinstance(item, Mapping)],
        session_id=(
            str(session["external_session_id"])
            if session.get("external_session_id") is not None
            else None
        ),
    )
    return {
        "schema": RESULT_SCHEMA,
        "reply": {"segments": [{"type": "text", "data": {"text": text}}]},
        "external_session_id": session_id,
    }


def main() -> None:
    request = json.load(sys.stdin)
    if not isinstance(request, Mapping):
        raise ValueError("invoke must be a JSON object")
    json.dump(handle(request), sys.stdout)


if __name__ == "__main__":
    main()

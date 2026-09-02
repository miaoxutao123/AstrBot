"""Generic invocation protocol and local session-store tests."""

from pathlib import Path

import pytest

from astrbot_gateway_agent.config import BridgeConfig
from astrbot_gateway_agent.protocol import RESULT_SCHEMA, parse_result
from astrbot_gateway_agent.runtime import AgentBridge
from astrbot_gateway_agent.sessions import SessionStore
from astrbot_gateway_sdk import GatewayEvent


def test_result_requires_canonical_schema_and_text() -> None:
    assert parse_result(
        {
            "schema": RESULT_SCHEMA,
            "session": {"external_session_id": "s1"},
            "reply": {"text": "hello"},
        }
    ) == ("hello", "s1")
    with pytest.raises(ValueError):
        parse_result({"schema": RESULT_SCHEMA, "reply": {}})


def test_session_store_persists_mapping(tmp_path: Path) -> None:
    path = tmp_path / "sessions.db"
    store = SessionStore(path)
    store.put("im/fake/a/private/1", "external-1")
    store.close()
    reopened = SessionStore(path)
    assert reopened.get("im/fake/a/private/1") == "external-1"
    reopened.close()


@pytest.mark.parametrize("setting", ["max_concurrency: 0", "max_pending: -1", "invoke_timeout: 0", "max_stdout_bytes: nope"])
def test_runtime_config_requires_positive_values(tmp_path: Path, setting: str) -> None:
    config = tmp_path / "agent-gateway.yaml"
    config.write_text("gateway:\n  url: http://gateway\n  api_key_env: KEY\nagent:\n  mode: command\n  command: [python, wrapper.py]\nruntime:\n  " + setting + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="runtime"):
        BridgeConfig.load(config)


class _Harness:
    async def invoke(self, value: dict[str, object]) -> dict[str, object]:
        assert value["input"]
        return {
            "schema": RESULT_SCHEMA,
            "session": {"external_session_id": "harness-1"},
            "reply": {"text": "echo: hello"},
        }


class _Gateway:
    def __init__(self) -> None:
        self.responses: list[str] = []

    async def respond(self, _event: GatewayEvent, text: str) -> dict[str, str]:
        self.responses.append(text)
        return {"status": "success"}


@pytest.mark.asyncio
async def test_bridge_current_conversation_closed_loop(tmp_path: Path) -> None:
    config = BridgeConfig(
        "http://gateway",
        "KEY",
        "im",
        "im.message",
        "command",
        ("ignored",),
        None,
        tmp_path / "sessions.db",
    )
    bridge = AgentBridge(config, "key")
    gateway = _Gateway()
    bridge.client = gateway  # type: ignore[assignment]
    bridge.invoker = _Harness()  # type: ignore[assignment]
    event = GatewayEvent.from_wire(
        {
            "id": "event-1",
            "type": "im.message",
            "source": {
                "family": "im",
                "adapter_type": "fake",
                "adapter_id": "main",
                "endpoint_id": "private:1",
            },
            "payload": {
                "schema": "im.message.v1",
                "data": {
                    "message_id": "message-1",
                    "conversation": {"type": "private", "id": "1"},
                    "sender": {"id": "1"},
                    "segments": [{"type": "text", "data": {"text": "hello"}}],
                },
            },
            "metadata": {},
        }
    )
    await bridge.handle(event)
    assert gateway.responses == ["echo: hello"]
    assert bridge.sessions.get("im/fake/main/private/1") == "harness-1"
    bridge.sessions.close()

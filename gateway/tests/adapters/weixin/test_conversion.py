from __future__ import annotations

import logging
from typing import Any

import pytest

from gateway.adapters.weixin.config import WeixinConfig
from gateway.adapters.weixin.inbound import convert_inbound_message
from gateway.adapters.weixin.session import WeixinSession, WeixinSessionStore
from gateway.core import AdapterContext, GatewayEvent
from gateway.media import MemoryMediaStore
from gateway.secrets import MemorySecretStore
from gateway.state import MemoryStateStore


class _MediaClient:
    async def download_media(self, item: dict[str, Any]) -> tuple[bytes, str | None]:
        return b"image", "image/png"


@pytest.mark.asyncio
async def test_unknown_weixin_item_is_preserved_as_raw() -> None:
    converted = await convert_inbound_message(
        "primary",
        {
            "from_user_id": "user-1",
            "message_id": "message-1",
            "item_list": [{"type": 999, "future_field": "kept"}],
        },
        _MediaClient(),  # type: ignore[arg-type]
        MemoryMediaStore(),
    )

    assert converted is not None
    assert converted.event.source.family == "im"
    assert converted.event.source.adapter_type == "weixin"
    assert converted.event.source.adapter_id == "primary"
    assert converted.event.type == "im.message"
    assert converted.event.payload.data["segments"][0] == {
        "type": "raw",
        "data": {
            "platform": "weixin",
            "segment_type": "message",
            "data": {
                "from_user_id": "user-1",
                "message_id": "message-1",
                "item_list": [{"type": 999, "future_field": "kept"}],
            },
        },
    }


@pytest.mark.asyncio
async def test_session_store_keeps_credentials_out_of_state() -> None:
    state = MemoryStateStore()
    secrets = MemorySecretStore()

    async def emit(_event: GatewayEvent) -> None:
        return None

    context = AdapterContext(
        family="im",
        adapter_type="weixin",
        adapter_id="primary",
        emit=emit,
        logger=logging.getLogger("test.weixin"),
        get_secret=lambda _key: None,
        report_state=lambda _state, _reason: None,
        media=MemoryMediaStore(),
        state=state,
        secrets=secrets,
    )
    session = WeixinSession(
        token="secret-token",
        account_id="account",
        base_url="https://example.invalid",
        cursor="cursor",
        context_tokens={"user-1": "context-secret"},
    )

    await WeixinSessionStore(context).save(
        session,
        WeixinConfig.from_mapping({"base_url": "https://example.invalid"}),
    )

    stored_state = await state.get("session")
    assert stored_state == {
        "account_id": "account",
        "base_url": "https://example.invalid",
        "cursor": "cursor",
    }
    assert await secrets.get("token") == "secret-token"
    assert await secrets.get("context_tokens") == '{"user-1":"context-secret"}'

"""Gateway IM to Weixin outbound protocol conversion."""

import uuid
from collections.abc import Mapping
from typing import Any

from gateway.media import MediaStore
from gateway.profiles.im import IMOutboundMessage

from .client import WeixinClient
from .errors import WeixinAuthenticationError, WeixinRequestError
from .media import prepare_outbound_media
from .session import WeixinSession, integer_value, string_value

SESSION_TIMEOUT_ERRCODE = -14


def check_result(result: Mapping[str, Any]) -> None:
    """Raise a stable error for a rejected Weixin response."""
    errcode = integer_value(result.get("errcode"))
    if errcode == SESSION_TIMEOUT_ERRCODE:
        raise WeixinAuthenticationError("Weixin session token expired")
    if integer_value(result.get("ret")) or errcode:
        raise WeixinRequestError("Weixin request was rejected")


async def send_message(
    user_id: str,
    outbound: IMOutboundMessage,
    client: WeixinClient,
    media_store: MediaStore,
    session: WeixinSession,
) -> str:
    """Send one supported outbound IM message."""
    if not session.token:
        raise WeixinAuthenticationError("Weixin authentication required")
    context_token = session.context_tokens.get(user_id)
    if not context_token:
        raise WeixinRequestError(
            "Weixin context token is unavailable; receive a message from this user first"
        )
    if outbound.reply_to:
        raise ValueError("Weixin outbound reply is not supported")
    items: list[dict[str, Any]] = []
    for segment in outbound.segments:
        if segment.type == "text":
            items.append({"type": 1, "text_item": {"text": segment.data["text"]}})
        elif segment.type in {"image", "video", "file"}:
            items.append(
                await prepare_outbound_media(
                    user_id, segment, client, media_store, session.token
                )
            )
        else:
            raise ValueError(f"Weixin segment is unsupported: {segment.type}")
    client_id = uuid.uuid4().hex
    result = await client.request(
        "POST",
        "ilink/bot/sendmessage",
        payload={
            "base_info": {"channel_version": "astrbot-gateway"},
            "msg": {
                "from_user_id": "",
                "to_user_id": user_id,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": items,
            },
        },
        token=session.token,
    )
    check_result(result)
    return client_id


async def send_typing(
    user_id: str, active: bool, client: WeixinClient, session: WeixinSession
) -> None:
    """Resolve a typing ticket and send a typing state."""
    if not session.token:
        raise WeixinAuthenticationError("Weixin authentication required")
    context_token = session.context_tokens.get(user_id)
    if not context_token:
        raise WeixinRequestError("Weixin context token is unavailable")
    config = await client.request(
        "POST",
        "ilink/bot/getconfig",
        payload={
            "ilink_user_id": user_id,
            "context_token": context_token,
            "base_info": {"channel_version": "astrbot-gateway"},
        },
        token=session.token,
    )
    ticket = string_value(config.get("typing_ticket"))
    if not ticket:
        raise WeixinRequestError("Weixin typing ticket is unavailable")
    result = await client.request(
        "POST",
        "ilink/bot/sendtyping",
        payload={
            "ilink_user_id": user_id,
            "typing_ticket": ticket,
            "status": 1 if active else 2,
            "base_info": {"channel_version": "astrbot-gateway"},
        },
        token=session.token,
    )
    check_result(result)

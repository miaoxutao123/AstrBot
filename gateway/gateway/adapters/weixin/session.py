"""Weixin session state and dynamic credential persistence."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from gateway.core import AdapterContext

from .config import WeixinConfig

SESSION_KEY = "session"
TOKEN_KEY = "token"
CONTEXT_TOKENS_KEY = "context_tokens"


def string_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int):
        return str(value).strip()
    return ""


def integer_value(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float | str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


@dataclass(slots=True)
class WeixinSession:
    """Mutable in-process Weixin session view."""

    token: str | None = None
    account_id: str | None = None
    base_url: str | None = None
    cursor: str = ""
    context_tokens: dict[str, str] = field(default_factory=dict)


class WeixinSessionStore:
    """Classify and persist Weixin state and credentials."""

    def __init__(self, context: AdapterContext) -> None:
        self._context = context

    async def restore(self) -> WeixinSession:
        value = await self._context.state.get(SESSION_KEY)
        metadata = value if isinstance(value, Mapping) else {}
        await self._migrate_plaintext(metadata)
        serialized_tokens = await self._context.secrets.get(CONTEXT_TOKENS_KEY)
        context_tokens: dict[str, str] = {}
        if serialized_tokens:
            try:
                tokens = json.loads(serialized_tokens)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "stored Weixin context credentials are invalid"
                ) from exc
            if not isinstance(tokens, Mapping):
                raise ValueError("stored Weixin context credentials are invalid")
            context_tokens = {
                string_value(key): string_value(token)
                for key, token in tokens.items()
                if string_value(key) and string_value(token)
            }
        return WeixinSession(
            token=await self._context.secrets.get(TOKEN_KEY),
            account_id=string_value(metadata.get("account_id")) or None,
            base_url=string_value(metadata.get("base_url")) or None,
            cursor=string_value(metadata.get("cursor")),
            context_tokens=context_tokens,
        )

    async def _migrate_plaintext(self, metadata: Mapping[object, object]) -> None:
        legacy_token = string_value(metadata.get("token"))
        legacy_tokens = metadata.get("context_tokens")
        normalized: dict[str, str] = {}
        if legacy_token:
            await self._context.secrets.set(TOKEN_KEY, legacy_token)
        if isinstance(legacy_tokens, Mapping):
            normalized = {
                string_value(key): string_value(token)
                for key, token in legacy_tokens.items()
                if string_value(key) and string_value(token)
            }
            if normalized:
                await self._context.secrets.set(
                    CONTEXT_TOKENS_KEY,
                    json.dumps(normalized, separators=(",", ":")),
                )
        if not legacy_token and not isinstance(legacy_tokens, Mapping):
            return
        if legacy_token and await self._context.secrets.get(TOKEN_KEY) != legacy_token:
            raise RuntimeError("Weixin token migration verification failed")
        serialized = json.dumps(normalized, separators=(",", ":"))
        if (
            normalized
            and await self._context.secrets.get(CONTEXT_TOKENS_KEY) != serialized
        ):
            raise RuntimeError(
                "Weixin context credential migration verification failed"
            )
        await self._context.state.set(
            SESSION_KEY,
            {
                "account_id": metadata.get("account_id"),
                "base_url": metadata.get("base_url"),
                "cursor": metadata.get("cursor", ""),
            },
        )

    async def save(self, session: WeixinSession, config: WeixinConfig) -> None:
        if not session.token:
            return
        await self._context.secrets.set(TOKEN_KEY, session.token)
        if session.context_tokens:
            await self._context.secrets.set(
                CONTEXT_TOKENS_KEY,
                json.dumps(session.context_tokens, separators=(",", ":")),
            )
        else:
            await self._context.secrets.delete(CONTEXT_TOKENS_KEY)
        await self._context.state.set(
            SESSION_KEY,
            {
                "account_id": session.account_id,
                "base_url": config.base_url,
                "cursor": session.cursor,
            },
        )

    async def invalidate(self, session: WeixinSession) -> None:
        session.token = None
        session.account_id = None
        session.cursor = ""
        session.context_tokens.clear()
        await self._context.state.delete(SESSION_KEY)
        await self._context.secrets.delete(TOKEN_KEY)
        await self._context.secrets.delete(CONTEXT_TOKENS_KEY)

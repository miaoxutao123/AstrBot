import pytest

from astrbot.core.long_term_memory.models import MemoryItem
from astrbot.core.long_term_memory.policy import MemoryReadPolicy
from astrbot.core.long_term_memory.reader import MemoryReader
from astrbot.core.long_term_memory.scope import (
    resolve_ltm_read_targets,
    resolve_ltm_scope,
)
from astrbot.core.platform.message_type import MessageType


class _DummyEvent:
    def __init__(
        self,
        *,
        msg_type: MessageType = MessageType.FRIEND_MESSAGE,
        unified_msg_origin: str = "qq:FriendMessage:session_001",
        sender_id: str = "user_001",
        platform_id: str = "qq",
        session_id: str = "session_001",
        extras: dict | None = None,
    ) -> None:
        self._msg_type = msg_type
        self.unified_msg_origin = unified_msg_origin
        self._sender_id = sender_id
        self._platform_id = platform_id
        self.session_id = session_id
        self._extras = extras or {}

    def get_message_type(self):
        return self._msg_type

    def get_sender_id(self):
        return self._sender_id

    def get_platform_id(self):
        return self._platform_id

    def get_extra(self, key: str, default=None):
        return self._extras.get(key, default)


class _FakeMemoryDB:
    def __init__(self, items: list[MemoryItem]):
        self._items = items
        self.last_scope_call: tuple | None = None
        self.last_scopes_call: tuple | None = None

    async def get_active_items_for_scope(
        self,
        scope: str,
        scope_id: str,
        min_confidence: float = 0.0,
        limit: int = 100,
    ) -> list[MemoryItem]:
        self.last_scope_call = (scope, scope_id, min_confidence, limit)
        return [
            item for item in self._items
            if item.scope == scope
            and item.scope_id == scope_id
            and item.status == "active"
            and item.confidence >= min_confidence
        ][:limit]

    async def get_active_items_for_scopes(
        self,
        scopes: list[tuple[str, str]],
        min_confidence: float = 0.0,
        limit: int = 300,
    ) -> list[MemoryItem]:
        self.last_scopes_call = (tuple(scopes), min_confidence, limit)
        allowed = set(scopes)
        return [
            item for item in self._items
            if (item.scope, item.scope_id) in allowed
            and item.status == "active"
            and item.confidence >= min_confidence
        ][:limit]


def _item(
    scope_id: str,
    mem_type: str,
    fact: str,
    fact_key: str,
    confidence: float = 0.9,
    importance: float = 0.8,
) -> MemoryItem:
    return MemoryItem(
        scope="user",
        scope_id=scope_id,
        type=mem_type,
        fact=fact,
        fact_key=fact_key,
        confidence=confidence,
        importance=importance,
        evidence_count=1,
        status="active",
    )


@pytest.mark.parametrize(
    "identity_cfg,expected_scope_id",
    [
        ({}, "qq:FriendMessage:session_001"),
        ({"user_scope_strategy": "sender_id"}, "user_001"),
        ({"user_scope_strategy": "platform_sender_id"}, "qq:user_001"),
        (
            {
                "user_scope_strategy": "sender_id",
                "cross_platform_aliases": {"qq:user_001": "global_todd"},
            },
            "global_todd",
        ),
    ],
)
def test_resolve_user_scope_with_identity_policy(identity_cfg, expected_scope_id):
    event = _DummyEvent()
    scope, scope_id = resolve_ltm_scope(
        event,
        ltm_cfg={"identity": identity_cfg},
    )
    assert scope == "user"
    assert scope_id == expected_scope_id


def test_resolve_group_scope_stays_on_umo():
    event = _DummyEvent(
        msg_type=MessageType.GROUP_MESSAGE,
        unified_msg_origin="qq:GroupMessage:group_777",
        sender_id="user_001",
        platform_id="qq",
    )
    scope, scope_id = resolve_ltm_scope(
        event,
        ltm_cfg={"identity": {"user_scope_strategy": "sender_id"}},
    )
    assert scope == "group"
    assert scope_id == "qq:GroupMessage:group_777"


def test_read_targets_include_legacy_umo_when_strategy_changes():
    event = _DummyEvent()
    scope, scope_id, extra = resolve_ltm_read_targets(
        event,
        ltm_cfg={
            "identity": {
                "user_scope_strategy": "sender_id",
                "include_legacy_umo_on_read": True,
            }
        },
    )
    assert scope == "user"
    assert scope_id == "user_001"
    assert ("user", "qq:FriendMessage:session_001") in extra


@pytest.mark.asyncio
async def test_retrieve_across_primary_and_legacy_scopes():
    db = _FakeMemoryDB(
        [
            _item(
                scope_id="global_todd",
                mem_type="preference",
                fact="用户偏好中文回答",
                fact_key="language_preference",
                confidence=0.92,
                importance=0.8,
            ),
            _item(
                scope_id="qq:FriendMessage:session_001",
                mem_type="profile",
                fact="用户昵称是 Todd",
                fact_key="nickname_todd",
                confidence=0.9,
                importance=0.75,
            ),
        ]
    )
    reader = MemoryReader(db)  # type: ignore[arg-type]

    ctx = await reader.retrieve_memory_context(
        scope="user",
        scope_id="global_todd",
        read_policy=MemoryReadPolicy(max_items=10, max_tokens=500),
        additional_scopes=[("user", "qq:FriendMessage:session_001")],
    )

    assert db.last_scopes_call is not None
    assert "用户偏好中文回答" in ctx
    assert "用户昵称是 Todd" in ctx


@pytest.mark.asyncio
async def test_retrieve_across_scopes_dedup_by_fact_key():
    db = _FakeMemoryDB(
        [
            _item(
                scope_id="global_todd",
                mem_type="preference",
                fact="用户喜欢简洁回答",
                fact_key="prefer_concise_reply",
                confidence=0.95,
                importance=0.8,
            ),
            _item(
                scope_id="qq:FriendMessage:session_001",
                mem_type="preference",
                fact="用户喜欢简洁回答",
                fact_key="prefer_concise_reply",
                confidence=0.7,
                importance=0.6,
            ),
        ]
    )
    reader = MemoryReader(db)  # type: ignore[arg-type]

    ctx = await reader.retrieve_memory_context(
        scope="user",
        scope_id="global_todd",
        read_policy=MemoryReadPolicy(max_items=10, max_tokens=500),
        additional_scopes=[("user", "qq:FriendMessage:session_001")],
    )

    assert ctx.count("用户喜欢简洁回答") == 1

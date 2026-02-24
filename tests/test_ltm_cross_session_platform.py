import pytest

from astrbot.core.long_term_memory.models import MemoryItem, MemoryRelation
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
    def __init__(self, items: list[MemoryItem], relations: list[MemoryRelation] | None = None):
        self._items = items
        self._relations = relations or []
        self.last_scope_call: tuple | None = None
        self.last_scopes_call: tuple | None = None
        self.last_relation_scope_call: tuple | None = None
        self.last_relation_scopes_call: tuple | None = None

    async def get_active_items_for_scope(
        self,
        scope: str,
        scope_id: str,
        min_confidence: float = 0.0,
        limit: int = 100,
        as_of=None,
    ) -> list[MemoryItem]:
        self.last_scope_call = (scope, scope_id, min_confidence, limit, as_of)
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
        as_of=None,
    ) -> list[MemoryItem]:
        self.last_scopes_call = (tuple(scopes), min_confidence, limit, as_of)
        allowed = set(scopes)
        return [
            item for item in self._items
            if (item.scope, item.scope_id) in allowed
            and item.status == "active"
            and item.confidence >= min_confidence
        ][:limit]

    async def get_active_relations_for_scope(
        self,
        scope: str,
        scope_id: str,
        min_confidence: float = 0.0,
        limit: int = 100,
        as_of=None,
    ) -> list[MemoryRelation]:
        self.last_relation_scope_call = (scope, scope_id, min_confidence, limit, as_of)
        return [
            rel for rel in self._relations
            if rel.scope == scope
            and rel.scope_id == scope_id
            and rel.status == "active"
            and rel.confidence >= min_confidence
        ][:limit]

    async def get_active_relations_for_scopes(
        self,
        scopes: list[tuple[str, str]],
        min_confidence: float = 0.0,
        limit: int = 300,
        as_of=None,
    ) -> list[MemoryRelation]:
        self.last_relation_scopes_call = (tuple(scopes), min_confidence, limit, as_of)
        allowed = set(scopes)
        return [
            rel for rel in self._relations
            if (rel.scope, rel.scope_id) in allowed
            and rel.status == "active"
            and rel.confidence >= min_confidence
        ][:limit]


class _FakeEmbeddingProvider:
    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        mapping = {
            "js 项目": [1.0, 0.0],
            "用户喜欢 TypeScript": [1.0, 0.0],
            "用户喜欢 Python": [0.0, 1.0],
        }
        return [mapping.get(text, [0.5, 0.5]) for text in texts]


class _FakeRelationEmbeddingProvider:
    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        mapping = {
            "海边度假": [1.0, 0.0],
            "location_pref lives_in 上海": [1.0, 0.0],
            "language_pref uses_language Rust": [0.0, 1.0],
        }
        return [mapping.get(text, [0.5, 0.5]) for text in texts]


def _item(
    scope_id: str,
    mem_type: str,
    fact: str,
    fact_key: str,
    subject_key: str | None = None,
    confidence: float = 0.9,
    importance: float = 0.8,
) -> MemoryItem:
    return MemoryItem(
        scope="user",
        scope_id=scope_id,
        type=mem_type,
        fact=fact,
        fact_key=fact_key,
        subject_key=subject_key,
        confidence=confidence,
        importance=importance,
        evidence_count=1,
        status="active",
    )


def _relation(
    scope_id: str,
    subject_key: str,
    predicate: str,
    object_text: str,
    confidence: float = 0.9,
) -> MemoryRelation:
    return MemoryRelation(
        scope="user",
        scope_id=scope_id,
        subject_key=subject_key,
        predicate=predicate,
        object_text=object_text,
        confidence=confidence,
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


@pytest.mark.parametrize("vector_quantization", ["none", "int8"])
@pytest.mark.asyncio
async def test_reader_hybrid_ranking_prefers_vector_match_when_available(vector_quantization):
    db = _FakeMemoryDB(
        [
            _item(
                scope_id="global_todd",
                mem_type="preference",
                fact="用户喜欢 Python",
                fact_key="prefer_python",
                confidence=0.9,
                importance=0.6,
            ),
            _item(
                scope_id="global_todd",
                mem_type="preference",
                fact="用户喜欢 TypeScript",
                fact_key="prefer_typescript",
                confidence=0.9,
                importance=0.6,
            ),
        ]
    )
    reader = MemoryReader(db)  # type: ignore[arg-type]
    policy = MemoryReadPolicy(
        max_items=2,
        max_tokens=500,
        recency_weight=0.0,
        importance_weight=0.0,
        similarity_weight=1.0,
        vector_quantization=vector_quantization,
    )

    ctx = await reader.retrieve_memory_context(
        scope="user",
        scope_id="global_todd",
        read_policy=policy,
        query_text="js 项目",
        embedding_provider=_FakeEmbeddingProvider(),
    )

    lines = [line for line in ctx.splitlines() if line.startswith("- ")]
    assert len(lines) >= 2
    assert "TypeScript" in lines[0]


@pytest.mark.asyncio
async def test_relation_first_strategy_boosts_items_by_relation_subject():
    db = _FakeMemoryDB(
        items=[
            _item(
                scope_id="global_todd",
                mem_type="profile",
                fact="用户当前城市未知",
                fact_key="current_city_unknown",
                subject_key="current_city",
                confidence=0.9,
                importance=0.6,
            ),
            _item(
                scope_id="global_todd",
                mem_type="profile",
                fact="用户喜欢烹饪",
                fact_key="hobby_cooking",
                subject_key="hobby_topic",
                confidence=0.9,
                importance=0.6,
            ),
        ],
        relations=[
            _relation(
                scope_id="global_todd",
                subject_key="current_city",
                predicate="lives_in",
                object_text="上海",
                confidence=0.95,
            ),
        ],
    )
    reader = MemoryReader(db)  # type: ignore[arg-type]
    policy = MemoryReadPolicy(
        max_items=2,
        max_tokens=500,
        strategy="relation_first",
        include_relations=False,
    )

    ctx = await reader.retrieve_memory_context(
        scope="user",
        scope_id="global_todd",
        read_policy=policy,
        query_text="上海",
    )

    lines = [line for line in ctx.splitlines() if line.startswith("- ")]
    assert len(lines) >= 2
    assert "当前城市未知" in lines[0]


@pytest.mark.asyncio
async def test_relation_vector_ranking_prefers_semantic_match():
    db = _FakeMemoryDB(
        items=[],
        relations=[
            _relation(
                scope_id="global_todd",
                subject_key="location_pref",
                predicate="lives_in",
                object_text="上海",
                confidence=0.82,
            ),
            _relation(
                scope_id="global_todd",
                subject_key="language_pref",
                predicate="uses_language",
                object_text="Rust",
                confidence=0.96,
            ),
        ],
    )
    reader = MemoryReader(db)  # type: ignore[arg-type]
    policy = MemoryReadPolicy(
        max_items=0,
        max_tokens=500,
        strategy="relation_first",
        include_relations=True,
        max_relation_lines=2,
        relation_use_vector=True,
        vector_quantization="int8",
    )

    ctx = await reader.retrieve_memory_context(
        scope="user",
        scope_id="global_todd",
        read_policy=policy,
        query_text="海边度假",
        embedding_provider=_FakeRelationEmbeddingProvider(),
    )

    lines = [line for line in ctx.splitlines() if line.startswith("- [relation]")]
    assert len(lines) >= 2
    assert "上海" in lines[0]


@pytest.mark.asyncio
async def test_relation_only_mode_suppresses_items_when_relations_exist():
    db = _FakeMemoryDB(
        items=[
            _item(
                scope_id="global_todd",
                mem_type="profile",
                fact="用户当前城市是上海",
                fact_key="current_city",
                subject_key="location_pref",
                confidence=0.92,
                importance=0.7,
            ),
        ],
        relations=[
            _relation(
                scope_id="global_todd",
                subject_key="location_pref",
                predicate="lives_in",
                object_text="上海",
                confidence=0.95,
            ),
        ],
    )
    reader = MemoryReader(db)  # type: ignore[arg-type]
    policy = MemoryReadPolicy(
        max_items=5,
        max_tokens=500,
        strategy="relation_first",
        include_relations=True,
        max_relation_lines=2,
        relation_only_mode=True,
    )

    ctx = await reader.retrieve_memory_context(
        scope="user",
        scope_id="global_todd",
        read_policy=policy,
        query_text="上海",
    )

    assert "[relation]" in ctx
    assert "[profile]" not in ctx


@pytest.mark.asyncio
async def test_relation_only_mode_falls_back_to_items_without_relations():
    db = _FakeMemoryDB(
        items=[
            _item(
                scope_id="global_todd",
                mem_type="profile",
                fact="用户职业是工程师",
                fact_key="occupation_engineer",
                subject_key="occupation",
                confidence=0.92,
                importance=0.7,
            ),
        ],
        relations=[],
    )
    reader = MemoryReader(db)  # type: ignore[arg-type]
    policy = MemoryReadPolicy(
        max_items=5,
        max_tokens=500,
        strategy="relation_first",
        include_relations=True,
        max_relation_lines=2,
        relation_only_mode=True,
    )

    ctx = await reader.retrieve_memory_context(
        scope="user",
        scope_id="global_todd",
        read_policy=policy,
        query_text="工程师",
    )

    assert "[relation]" not in ctx
    assert "[profile]" in ctx

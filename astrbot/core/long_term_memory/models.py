"""SQLModel definitions for the Long-Term Memory system."""

import uuid

from sqlmodel import JSON, Field, SQLModel, Text, UniqueConstraint

from astrbot.core.db.po import TimestampMixin


class MemoryEvent(TimestampMixin, SQLModel, table=True):
    """Raw source event recorded for memory extraction.

    Stores messages, tool results, and system signals that may
    contain facts worth persisting in long-term memory.
    """

    __tablename__: str = "memory_events"

    id: int | None = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"autoincrement": True},
    )
    event_id: str = Field(
        max_length=36,
        nullable=False,
        unique=True,
        default_factory=lambda: str(uuid.uuid4()),
    )
    scope: str = Field(max_length=32, nullable=False)
    """'user', 'group', 'project', 'global'"""
    scope_id: str = Field(max_length=255, nullable=False)
    """e.g. user_id, group unified_msg_origin"""
    source_type: str = Field(max_length=32, nullable=False)
    """'message', 'tool_result', 'system'"""
    source_role: str = Field(max_length=32, nullable=False)
    """'user', 'assistant', 'tool', 'system'"""
    content: dict = Field(sa_type=JSON, nullable=False)
    """Raw content dict"""
    platform_id: str | None = Field(default=None, max_length=255)
    session_id: str | None = Field(default=None, max_length=255)
    processed: bool = Field(default=False, nullable=False)
    """Whether this event has been processed for memory extraction"""


class MemoryItem(TimestampMixin, SQLModel, table=True):
    """Normalized memory unit — a single structured fact.

    Each item has a scope (user/group/project/global), a type,
    and a confidence score. Items can be active, shadow, disabled,
    or expired.
    """

    __tablename__: str = "memory_items"

    id: int | None = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"autoincrement": True},
    )
    memory_id: str = Field(
        max_length=36,
        nullable=False,
        unique=True,
        default_factory=lambda: str(uuid.uuid4()),
    )
    scope: str = Field(max_length=32, nullable=False)
    scope_id: str = Field(max_length=255, nullable=False)
    type: str = Field(max_length=32, nullable=False)
    """'profile', 'preference', 'task_state', 'constraint', 'episode'"""
    fact: str = Field(sa_type=Text, nullable=False)
    """Compact natural-language fact"""
    fact_key: str = Field(max_length=255, nullable=False)
    """Symbolic dedup key (lowered, normalized)"""
    confidence: float = Field(default=0.5, nullable=False)
    """0.0–1.0"""
    importance: float = Field(default=0.5, nullable=False)
    """0.0–1.0"""
    evidence_count: int = Field(default=1, nullable=False)
    ttl_days: int | None = Field(default=None)
    """Auto-expire after N days (None = permanent)"""
    status: str = Field(default="shadow", max_length=32, nullable=False)
    """'active', 'shadow', 'disabled', 'expired', 'consolidated'"""
    consolidation_count: int = Field(default=0, nullable=False)
    """Number of times this item has been part of a consolidation merge"""

    __table_args__ = (
        UniqueConstraint(
            "scope",
            "scope_id",
            "fact_key",
            name="uix_memory_item_scope_key",
        ),
    )


class MemoryEvidence(SQLModel, table=True):
    """Links a MemoryItem to one or more MemoryEvents.

    Tracks how each memory item was extracted and from which
    source event, providing full provenance.
    """

    __tablename__: str = "memory_evidence"

    id: int | None = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"autoincrement": True},
    )
    memory_id: str = Field(max_length=36, nullable=False)
    """References MemoryItem.memory_id"""
    event_id: str = Field(max_length=36, nullable=False)
    """References MemoryEvent.event_id"""
    extraction_method: str = Field(max_length=32, nullable=False)
    """'llm_extract', 'rule', 'user_explicit'"""
    extraction_meta: dict | None = Field(default=None, sa_type=JSON)
    """Model used, prompt hash, confidence detail"""

    __table_args__ = (
        UniqueConstraint(
            "memory_id",
            "event_id",
            name="uix_memory_evidence_mem_evt",
        ),
    )

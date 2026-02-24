"""SQLModel definitions for the Long-Term Memory system."""

import uuid
from datetime import datetime

from sqlalchemy import Index
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
    attempt_count: int = Field(default=0, nullable=False)
    """Number of extraction attempts for this event"""
    next_retry_at: datetime | None = Field(default=None)
    """When this event becomes eligible for retry"""
    last_error: str | None = Field(default=None, sa_type=Text)
    """Last extraction/pipeline error summary"""
    dead_letter: bool = Field(default=False, nullable=False)
    """True when retries exceeded and event should no longer be processed"""

    __table_args__ = (
        Index(
            "idx_memory_events_scope_scope_id_created_at",
            "scope",
            "scope_id",
            "created_at",
        ),
        Index(
            "idx_memory_events_retry_window",
            "processed",
            "dead_letter",
            "next_retry_at",
            "created_at",
        ),
    )


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
    subject_key: str | None = Field(default=None, max_length=255)
    """Stable concept key for temporal supersession/conflict handling"""
    confidence: float = Field(default=0.5, nullable=False)
    """0.0–1.0"""
    importance: float = Field(default=0.5, nullable=False)
    """0.0–1.0"""
    evidence_count: int = Field(default=1, nullable=False)
    ttl_days: int | None = Field(default=None)
    """Auto-expire after N days (None = permanent)"""
    status: str = Field(default="shadow", max_length=32, nullable=False)
    """'active', 'shadow', 'disabled', 'expired', 'consolidated', 'superseded'"""
    valid_at: datetime | None = Field(default=None)
    """When this memory becomes effective; None means immediate"""
    invalid_at: datetime | None = Field(default=None)
    """When this memory stops being effective; None means still valid"""
    superseded_by: str | None = Field(default=None, max_length=36)
    """memory_id of the newer item that superseded this fact"""
    consolidation_count: int = Field(default=0, nullable=False)
    """Number of times this item has been part of a consolidation merge"""

    __table_args__ = (
        UniqueConstraint(
            "scope",
            "scope_id",
            "fact_key",
            name="uix_memory_item_scope_key",
        ),
        Index(
            "idx_memory_items_scope_scope_id_status_conf_updated",
            "scope",
            "scope_id",
            "status",
            "confidence",
            "updated_at",
        ),
        Index(
            "idx_memory_items_scope_scope_id_type_status_updated",
            "scope",
            "scope_id",
            "type",
            "status",
            "updated_at",
        ),
        Index(
            "idx_memory_items_status_updated",
            "status",
            "updated_at",
        ),
        Index(
            "idx_memory_items_scope_scope_id_type_subject_validity",
            "scope",
            "scope_id",
            "type",
            "subject_key",
            "status",
            "invalid_at",
            "updated_at",
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
        Index("idx_memory_evidence_event_id", "event_id"),
    )


class MemoryRelation(TimestampMixin, SQLModel, table=True):
    """Structured relation derived from memory items (graph-lite layer)."""

    __tablename__: str = "memory_relations"

    id: int | None = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"autoincrement": True},
    )
    relation_id: str = Field(
        max_length=36,
        nullable=False,
        unique=True,
        default_factory=lambda: str(uuid.uuid4()),
    )
    scope: str = Field(max_length=32, nullable=False)
    scope_id: str = Field(max_length=255, nullable=False)
    subject_key: str = Field(max_length=255, nullable=False)
    predicate: str = Field(max_length=64, nullable=False)
    object_text: str = Field(sa_type=Text, nullable=False)
    confidence: float = Field(default=0.5, nullable=False)
    evidence_count: int = Field(default=1, nullable=False)
    status: str = Field(default="active", max_length=32, nullable=False)
    """'active', 'superseded', 'disabled'"""
    valid_at: datetime | None = Field(default=None)
    invalid_at: datetime | None = Field(default=None)
    superseded_by: str | None = Field(default=None, max_length=36)
    """relation_id of the newer relation that superseded this one"""
    memory_id: str | None = Field(default=None, max_length=36)
    """Source MemoryItem.memory_id"""
    memory_type: str | None = Field(default=None, max_length=32)

    __table_args__ = (
        Index(
            "idx_memory_relations_scope_scope_id_status_conf_updated",
            "scope",
            "scope_id",
            "status",
            "confidence",
            "updated_at",
        ),
        Index(
            "idx_memory_relations_scope_scope_id_subject_pred_status_validity",
            "scope",
            "scope_id",
            "subject_key",
            "predicate",
            "status",
            "invalid_at",
            "updated_at",
        ),
    )

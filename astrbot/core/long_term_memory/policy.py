"""Policy dataclasses for the Long-Term Memory system."""

from dataclasses import dataclass, field


VALID_MEMORY_TYPES = ("profile", "preference", "task_state", "constraint", "episode")
VALID_WRITE_MODES = ("shadow", "auto", "manual")
VALID_STATUSES = ("active", "shadow", "disabled", "expired", "consolidated", "superseded")

DEFAULT_RETENTION_DAYS = {
    "profile": -1,
    "preference": 90,
    "task_state": 7,
    "constraint": -1,
    "episode": 30,
}


@dataclass
class MemoryWritePolicy:
    enable: bool = True
    mode: str = "shadow"
    min_confidence: float = 0.6
    min_evidence_count: int = 1
    allowed_types: list[str] = field(
        default_factory=lambda: list(VALID_MEMORY_TYPES),
    )
    max_writes_per_session: int = 10
    max_writes_per_hour: int = 50
    max_items_per_scope: int = 200
    require_approval_types: list[str] = field(default_factory=list)
    eviction_enabled: bool = True
    eviction_buffer_ratio: float = 0.9
    enable_temporal_supersede: bool = True
    temporal_conflict_types: list[str] = field(
        default_factory=lambda: ["profile", "preference", "task_state", "constraint"],
    )

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryWritePolicy":
        return cls(
            enable=bool(d.get("enable", True)),
            mode=str(d.get("mode", "shadow")),
            min_confidence=float(d.get("min_confidence", 0.6)),
            min_evidence_count=int(d.get("min_evidence_count", 1)),
            allowed_types=list(d.get("allowed_types", list(VALID_MEMORY_TYPES))),
            max_writes_per_session=int(d.get("max_writes_per_session", 10)),
            max_writes_per_hour=int(d.get("max_writes_per_hour", 50)),
            max_items_per_scope=int(d.get("max_items_per_scope", 200)),
            require_approval_types=list(d.get("require_approval_types", [])),
            eviction_enabled=bool(d.get("eviction_enabled", True)),
            eviction_buffer_ratio=float(d.get("eviction_buffer_ratio", 0.9)),
            enable_temporal_supersede=bool(d.get("enable_temporal_supersede", True)),
            temporal_conflict_types=list(
                d.get(
                    "temporal_conflict_types",
                    ["profile", "preference", "task_state", "constraint"],
                )
            ),
        )


@dataclass
class MemoryReadPolicy:
    enable: bool = True
    max_items: int = 15
    max_tokens: int = 800
    max_per_type: int = 5
    min_confidence: float = 0.5
    recency_weight: float = 0.3
    importance_weight: float = 0.4
    similarity_weight: float = 0.3
    strategy: str = "balanced"
    include_relations: bool = False
    max_relation_lines: int = 5
    relation_use_vector: bool = True
    vector_quantization: str = "none"
    relation_only_mode: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryReadPolicy":
        return cls(
            enable=bool(d.get("enable", True)),
            max_items=int(d.get("max_items", 15)),
            max_tokens=int(d.get("max_tokens", 800)),
            max_per_type=int(d.get("max_per_type", 5)),
            min_confidence=float(d.get("min_confidence", 0.5)),
            recency_weight=float(d.get("recency_weight", 0.3)),
            importance_weight=float(d.get("importance_weight", 0.4)),
            similarity_weight=float(d.get("similarity_weight", 0.3)),
            strategy=str(d.get("strategy", "balanced")),
            include_relations=bool(d.get("include_relations", False)),
            max_relation_lines=int(d.get("max_relation_lines", 5)),
            relation_use_vector=bool(d.get("relation_use_vector", True)),
            vector_quantization=str(d.get("vector_quantization", "none")),
            relation_only_mode=bool(d.get("relation_only_mode", False)),
        )


@dataclass
class MemoryMaintenancePolicy:
    event_retention_days: int = 7
    maintenance_cron: str = "0 3 * * *"
    enable_consolidation: bool = False
    consolidation_cron: str = "0 4 * * 0"

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryMaintenancePolicy":
        return cls(
            event_retention_days=int(d.get("event_retention_days", 7)),
            maintenance_cron=str(d.get("maintenance_cron", "0 3 * * *")),
            enable_consolidation=bool(d.get("enable_consolidation", False)),
            consolidation_cron=str(d.get("consolidation_cron", "0 4 * * 0")),
        )

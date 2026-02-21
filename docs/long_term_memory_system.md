# Stable and Controllable Long-Term Memory System

This document proposes a production-ready long-term memory design for AstrBot that is:

- stable under noisy conversations and tool errors,
- controllable by operators and users,
- safe against self-iteration overfitting,
- compatible with existing project-context and resilience modules.

---

## 1. Core Principles

1. Memory is not chat history.
   - Keep short-term context and long-term memory separate.
   - Store only compact, structured, useful facts in LTM.
2. Every memory must have evidence.
   - A memory item is linked to one or more source events/messages/tools.
   - No source = no promotion to durable memory.
3. Retrieval must be bounded.
   - Strict budget for number of memory items and total tokens per request.
4. Memory writes are policy-driven.
   - Write policy can run in shadow mode before auto-apply.

---

## 2. Data Model

### 2.1 SQLModel Tables (in `astrbot/core/db/po.py`)

#### `MemoryEvent` — raw source events

| Column        | Type          | Description                                      |
|---------------|---------------|--------------------------------------------------|
| id            | int (PK, auto)| Internal row id                                  |
| event_id      | str (uuid4)   | Unique event identifier                          |
| scope         | str           | `"user"`, `"group"`, `"project"`, `"global"`     |
| scope_id      | str           | e.g. user_id, group unified_msg_origin           |
| source_type   | str           | `"message"`, `"tool_result"`, `"system"`         |
| source_role   | str           | `"user"`, `"assistant"`, `"tool"`, `"system"`    |
| content       | JSON          | Raw content dict (text, tool name/args/result)   |
| platform_id   | str \| None   | Originating platform id                          |
| session_id    | str \| None   | Conversation / session id                        |
| created_at    | datetime      | Event timestamp (TimestampMixin)                 |

#### `MemoryItem` — normalized memory unit

| Column        | Type          | Description                                      |
|---------------|---------------|--------------------------------------------------|
| id            | int (PK, auto)| Internal row id                                  |
| memory_id     | str (uuid4)   | Unique memory identifier                         |
| scope         | str           | Same as event scope                              |
| scope_id      | str           | Same as event scope_id                           |
| type          | str           | `"profile"`, `"preference"`, `"task_state"`, `"constraint"`, `"episode"` |
| fact          | str (Text)    | Compact natural-language fact                     |
| fact_key      | str           | Symbolic dedup key (lowered, normalized)          |
| confidence    | float         | 0.0–1.0, extraction confidence                   |
| importance    | float         | 0.0–1.0, estimated relevance weight              |
| evidence_count| int           | Number of independent confirming events           |
| ttl_days      | int \| None   | Auto-expire after N days (None = permanent)       |
| status        | str           | `"active"`, `"shadow"`, `"disabled"`, `"expired"` |
| created_at    | datetime      | First extracted                                   |
| updated_at    | datetime      | Last confirmed / updated                          |

**Unique constraint**: (`scope`, `scope_id`, `fact_key`)

#### `MemoryEvidence` — links memory to events

| Column        | Type          | Description                                      |
|---------------|---------------|--------------------------------------------------|
| id            | int (PK, auto)| Internal row id                                  |
| memory_id     | str           | FK to MemoryItem.memory_id                       |
| event_id      | str           | FK to MemoryEvent.event_id                       |
| extraction_method | str       | `"llm_extract"`, `"rule"`, `"user_explicit"`     |
| extraction_meta   | JSON      | Model used, prompt hash, confidence detail       |
| created_at    | datetime      | When evidence was linked                          |

### 2.2 Vector Storage

Reuse existing `BaseVecDB` / FAISS implementation (`astrbot/core/db/vec_db/`).

- Each `MemoryItem` optionally has an embedding stored in a dedicated VecDB namespace: `ltm_{scope}_{scope_id}`.
- Embedding is computed from `fact` text using the configured embedding provider.
- Updated on insert and on fact text change.

### 2.3 Memory Types

| Type          | Stability | TTL Default | Example                                          |
|---------------|-----------|-------------|--------------------------------------------------|
| `profile`     | high      | None        | "User's name is Alice"                           |
| `preference`  | medium    | 90 days     | "User prefers Python over Java"                  |
| `task_state`  | low       | 7 days      | "Migration to v2 API is 60% complete"            |
| `constraint`  | high      | None        | "Never use sudo in code suggestions"             |
| `episode`     | medium    | 30 days     | "Debugged OOM issue in production on 2025-03-01" |

---

## 3. Write Pipeline (Ingestion)

### 3.1 Architecture

```
Message/ToolResult
      │
      ▼
┌──────────────────┐
│  Event Recorder  │  → MemoryEvent table
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Candidate Extract│  → LLM-based extraction (async)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Dedup & Merge   │  → fact_key match + semantic similarity
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Confidence Score │  → source quality × repetition × contradiction
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Policy Gate    │  → min_confidence, max_writes, allowed_types
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Persist + Embed │  → MemoryItem + MemoryEvidence + VecDB
└────────┴─────────┘
```

### 3.2 Candidate Extraction

Use a compact LLM prompt to extract facts from conversation turns. Prompt template:

```
Given this conversation segment, extract any long-term facts worth remembering.
For each fact, output JSON:
{"type": "profile|preference|task_state|constraint|episode",
 "fact": "concise statement",
 "fact_key": "normalized_key",
 "confidence": 0.0-1.0,
 "importance": 0.0-1.0}
Only extract genuinely useful, non-trivial facts. Output [] if nothing is worth remembering.
```

Extraction runs **asynchronously** after the LLM response is sent — not in the hot path.

### 3.3 Dedup & Merge

1. Generate `fact_key` = lowercase, strip punctuation, first 128 chars.
2. Query existing items by (`scope`, `scope_id`, `fact_key`).
3. If exact key match → increment `evidence_count`, update `confidence` (weighted average), link new evidence.
4. If no key match → check semantic similarity (cosine > 0.85) against existing items of same scope.
   - If similar item found → merge: update fact text if newer confidence is higher, add evidence link.
   - Otherwise → create new MemoryItem.

### 3.4 Confidence Scoring

```python
confidence = base_confidence * source_quality_weight * repetition_bonus * (1 - contradiction_penalty)
```

- `base_confidence`: from LLM extraction output (0.0–1.0).
- `source_quality_weight`: `user_explicit=1.0`, `llm_extract=0.8`, `tool_result=0.7`.
- `repetition_bonus`: `min(1.0, 1.0 + 0.1 * (evidence_count - 1))`.
- `contradiction_penalty`: 0.5 if an existing item with same scope contradicts this fact (detected by LLM or keyword heuristic).

### 3.5 Write Policy (Configurable)

```python
@dataclass
class MemoryWritePolicy:
    enable: bool = True
    mode: str = "shadow"            # "shadow" | "auto" | "manual"
    min_confidence: float = 0.6
    min_evidence_count: int = 1
    allowed_types: list[str] = field(default_factory=lambda: ["profile","preference","task_state","constraint","episode"])
    max_writes_per_session: int = 10
    max_writes_per_hour: int = 50
    max_items_per_scope: int = 200
    require_approval_types: list[str] = field(default_factory=list)  # e.g. ["constraint"]
```

- `shadow` mode: writes go to status=`"shadow"`, visible in dashboard but not injected into prompts.
- `auto` mode: writes go to status=`"active"` if policy thresholds are met.
- `manual` mode: all candidates are queued for human approval.

---

## 4. Read Pipeline (Retrieval)

### 4.1 Architecture

```
LLM Request
      │
      ▼
┌──────────────────┐
│  Scope Resolver  │  → determine (scope, scope_id) from event
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Hybrid Retrieval │  → symbolic filter + vector similarity + recency/importance
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Diversity Filter │  → cap same-type, drop expired/low-confidence
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Budget Enforcer  │  → max_items, max_tokens
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Prompt Formatter │  → bullet list with provenance tags
└────────┴─────────┘
```

### 4.2 Retrieval Budget (Configurable)

```python
@dataclass
class MemoryReadPolicy:
    enable: bool = True
    max_items: int = 15
    max_tokens: int = 800
    max_per_type: int = 5          # diversity cap
    min_confidence: float = 0.5
    recency_weight: float = 0.3    # weight for time decay
    importance_weight: float = 0.4  # weight for importance score
    similarity_weight: float = 0.3  # weight for semantic similarity
```

### 4.3 Hybrid Ranking Score

```
score = similarity_weight * cosine_sim
      + importance_weight * item.importance
      + recency_weight * time_decay(item.updated_at)
```

Where `time_decay(t) = 1.0 / (1.0 + days_since(t) / 30.0)`.

### 4.4 Prompt Injection Format

Injected as a system-level memory context block before the user message:

```
[Long-term Memory]
- [profile] User's name is Alice (confidence: 0.95)
- [preference] Prefers concise code examples (confidence: 0.82)
- [constraint] Do not use deprecated APIs (confidence: 0.90)
- [episode] Completed auth module refactor on 2025-02-01 (confidence: 0.75)
[End Memory]
```

Token budget is enforced by truncating lower-scored items.

---

## 5. Anti-Overfitting for Self-Iteration

When LLM iterates tools/skills policies automatically, avoid overfitting with the following guardrails:

1. **Shadow mode first**
   - New policy runs in dry-run mode and logs hypothetical decisions.
2. **Holdout replay set**
   - Evaluate policy on fixed historical sessions not used for fitting.
3. **Multi-objective score**
   - success rate + latency + token cost + safety violations.
4. **Drift detector**
   - detect sudden behavior shifts after policy changes.
   - Metric: cosine similarity of memory distribution snapshots before/after.
5. **Rollback switch**
   - instant revert to previous stable policy snapshot.
6. **Diversity regularization**
   - avoid repeatedly selecting one tool path when alternatives are valid.

---

## 6. Implementation File Layout

```
astrbot/core/long_term_memory/
├── __init__.py
├── models.py              # MemoryEvent, MemoryItem, MemoryEvidence SQLModels
├── manager.py             # LTMManager - central coordinator
├── writer.py              # MemoryWriter - write pipeline
├── reader.py              # MemoryReader - read pipeline
├── extractor.py           # LLM-based candidate extraction
├── policy.py              # MemoryWritePolicy, MemoryReadPolicy dataclasses
└── db.py                  # Database operations for memory tables

astrbot/dashboard/routes/
└── long_term_memory.py    # Dashboard API routes for memory audit
```

---

## 7. Runtime Integration Points in AstrBot

### 7.1 Before LLM call (`MainAgentHooks.on_agent_begin`)

In `astrbot/core/astr_agent_hooks.py`, extend `MainAgentHooks.on_agent_begin`:

```python
async def on_agent_begin(self, run_context):
    # Retrieve memory bundle and inject into system prompt
    event = run_context.context.event
    memory_context = await ltm_manager.retrieve_memory_context(event)
    if memory_context:
        # Prepend to the first system message
        messages = run_context.messages
        if messages and messages[0].role == "system":
            messages[0].content = memory_context + "\n" + messages[0].content
```

### 7.2 After LLM response (`MainAgentHooks.on_agent_done`)

Existing hook already fires. Add memory candidate recording:

```python
async def on_agent_done(self, run_context, llm_response):
    # ... existing logic ...
    # Record event and schedule async extraction
    await ltm_manager.record_conversation_turn(run_context, llm_response)
```

### 7.3 After tool execution (`MainAgentHooks.on_tool_end`)

Record tool results as memory events:

```python
async def on_tool_end(self, run_context, tool, tool_args, tool_result):
    # ... existing logic ...
    await ltm_manager.record_tool_event(run_context, tool, tool_args, tool_result)
```

### 7.4 Background tasks

Register a periodic background task for:
- Batch extraction of memory candidates from buffered events.
- TTL expiration sweep (mark expired items as `status="expired"`).
- Memory compaction (merge near-duplicate items).

### 7.5 Dashboard API

| Endpoint                           | Method | Description                         |
|------------------------------------|--------|-------------------------------------|
| `/api/ltm/items`                   | GET    | List memory items (paginated, filterable) |
| `/api/ltm/items/{memory_id}`       | GET    | Get single memory item with evidence |
| `/api/ltm/items/{memory_id}`       | PATCH  | Update status/importance/ttl         |
| `/api/ltm/items/{memory_id}`       | DELETE | Delete a memory item                 |
| `/api/ltm/events`                  | GET    | List memory events (paginated)       |
| `/api/ltm/stats`                   | GET    | Memory statistics per scope          |
| `/api/ltm/policy`                  | GET    | Get current write/read policy        |
| `/api/ltm/policy`                  | PUT    | Update write/read policy             |
| `/api/ltm/export`                  | GET    | Export memory items as JSON          |
| `/api/ltm/import`                  | POST   | Import memory items from JSON        |

---

## 8. Configuration (in `DEFAULT_CONFIG`)

```python
"provider_ltm_settings": {
    # ... existing fields ...
    "long_term_memory": {
        "enable": False,
        "write_policy": {
            "mode": "shadow",           # "shadow" | "auto" | "manual"
            "min_confidence": 0.6,
            "min_evidence_count": 1,
            "allowed_types": ["profile", "preference", "task_state", "constraint", "episode"],
            "max_writes_per_session": 10,
            "max_writes_per_hour": 50,
            "max_items_per_scope": 200,
            "require_approval_types": [],
        },
        "read_policy": {
            "enable": True,
            "max_items": 15,
            "max_tokens": 800,
            "max_per_type": 5,
            "min_confidence": 0.5,
            "recency_weight": 0.3,
            "importance_weight": 0.4,
            "similarity_weight": 0.3,
        },
        "identity": {
            "user_scope_strategy": "unified_msg_origin",
            "cross_platform_aliases": {},
            "include_legacy_umo_on_read": True
        },
        "extraction_provider_id": "",   # which LLM provider to use for extraction (empty = default)
        "embedding_provider_id": "",    # which embedding provider to use (empty = default)
        "retention_days": {
            "profile": -1,              # -1 = permanent
            "preference": 90,
            "task_state": 7,
            "constraint": -1,
            "episode": 30,
        },
        "emergency_read_only": False,
    },
},
```

---

## 9. Operational Controls

Expose operator-level controls:

- memory write enable/disable by scope (via dashboard or config)
- retention days per memory type (configurable, auto-sweep by background task)
- max memory items per scope (enforced at write time, oldest low-importance evicted)
- emergency read-only mode (config flag, disables all writes instantly)
- export/import via dashboard API (JSON format with checksums)

---

## 10. Rollout Plan

### Phase 1 — Safe Baseline (This PR)

- [x] Enrich design document
- [ ] SQLModel tables: `MemoryEvent`, `MemoryItem`, `MemoryEvidence`
- [ ] Database layer: CRUD operations in `SQLiteDatabase`
- [ ] Database migration for existing databases
- [ ] `MemoryWritePolicy` / `MemoryReadPolicy` dataclasses
- [ ] `LTMManager` skeleton with shadow-mode write pipeline
- [ ] Event recording hooks in `MainAgentHooks` (on_agent_done, on_tool_end)
- [ ] Basic LLM extraction prompt
- [ ] Configuration entries in `DEFAULT_CONFIG`
- [ ] Dashboard API: list/get/update/delete memory items

### Phase 2 — Online Value

- [ ] Automatic retrieval injection in `on_agent_begin` with strict budget
- [ ] Hybrid ranking (symbolic + vector similarity + recency)
- [ ] Dedup & merge with semantic similarity
- [ ] Memory audit dashboard frontend
- [ ] Background task: TTL sweep, compaction

### Phase 3 — Self-Iteration with Guardrails

- [ ] Policy auto-tuning on holdout replay
- [ ] Drift monitor + rollback automation
- [ ] Tool/memory co-optimization under safety constraints

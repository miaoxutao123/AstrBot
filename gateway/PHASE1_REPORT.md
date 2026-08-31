# Phase 1 Report

## Implemented

- Standalone `agent-transport-gateway` Python project with no runtime dependencies.
- Transport-neutral `EndpointRef`, `Payload`, `GatewayEvent`, `GatewayCommand`,
  `CommandResult`, and `Capability` models.
- Stable error model and required error codes.
- Minimal `TransportAdapter`, `AdapterContext`, and versioned descriptor contract.
- Adapter factory/instance registry with standard Python entry-point discovery.
- Failure-isolated discovery results, so one broken third-party entry point does
  not prevent healthy adapters from loading.
- Per-adapter runtime states, concurrent lifecycle management, startup/shutdown
  failure isolation, runtime health reporting, capability enforcement, and safe
  command results.
- Bounded in-memory event bus with awaited backpressure, subscriber exception
  isolation, atomic shutdown admission, logging context, and graceful draining.
- Transport-metadata router and ordered top-level lifecycle.
- Fake IM, temperature sensor, and robot adapters.
- Phase 0 extraction audit, architecture, protocol, and provenance documents.

## Not implemented

The following are intentionally outside Phase 1 and have not been started:

- HTTP, WebSocket, webhook, authentication, API keys, or caller authorization;
- configuration file loader, SQLite storage, dedup persistence, or delivery state;
- real OneBot, Telegram, or Weixin adapters and their SDK dependencies;
- durable event replay or external event-bus backends;
- MCP server or client;
- WebUI or ChatUI;
- Agent, LLM, provider, prompt, tool, memory, RAG, or plugin behavior.

The project stops before Phase 2 as required.

## Decoupling from AstrBot

Gateway Core imports no `astrbot` module. It does not use `AstrMessageEvent`,
`AstrBotMessage`, `MessageChain`, `MessageSesion`, `Platform`, `PlatformManager`,
`PipelineScheduler`, Star registries, providers, conversations, or metrics. Real
platform SDKs are also absent from Core.

Only architectural lessons were retained: independent adapter lifecycle, explicit
status, graceful termination, protocol conversion, and transport error isolation.
All Phase 1 implementation code is new.

## Current dependency tree

Runtime:

```text
agent-transport-gateway
└── Python standard library
    ├── asyncio
    ├── logging
    ├── dataclasses
    ├── enum
    ├── importlib.metadata
    ├── os
    ├── time
    ├── typing
    └── uuid
```

Development-only tools:

```text
pytest
pytest-asyncio
ruff
mypy
```

No OpenAI, Anthropic, Google GenAI, FAISS, MCP, AstrBot, IM SDK, hardware SDK,
database, API server, document, or media package is installed by the project.

## Verification

- Tests: 23 passed.
- Ruff: clean.
- Mypy strict mode and Pyright basic mode: clean across the source/test tree.
- Forbidden import scan: no AstrBot, AI SDK, MCP, HTTP API framework, or platform
  SDK imports in `gateway/gateway`.

Covered behavior includes model validation, unknown payload pass-through, registry
creation, duplicate rejection, isolated discovery failure, bounded-queue
backpressure, concurrent publish/stop admission, subscriber exception isolation,
graceful drain, transport-only routing, adapter contract conformance, source
spoofing rejection, sensor event delivery, robot command execution, degraded/recover
health reporting, offline and unsupported-command errors, and one-adapter startup
failure isolation.

Gateway has an independent `.github/workflows/gateway-ci.yml` quality gate for
Python 3.10 and 3.13. It runs pytest, Ruff formatting and linting, Mypy, and Pyright
when Gateway files or the workflow change.

## AstrBot adapter migration risks

### OneBot v11

- Protocol parsing and AstrBot component construction are interleaved.
- Reply, member, and file resolution perform network calls during conversion.
- Unknown segments are sometimes ignored rather than preserved as `raw`.
- Reverse WebSocket shutdown accesses private SDK state.

### Telegram

- Transport command registration is coupled to the Star plugin registry.
- Streaming output behavior is coupled to agent result generators.
- Media-group timing and temporary-file ownership need isolated tests.
- SDK errors must map to stable Gateway errors and capabilities.

### Weixin

- One large adapter combines login, QR state, polling, persistence, media crypto,
  reply cache, typing, conversion, and sending.
- Tokens and session state currently flow through AstrBot configuration/files.
- Login and persistent-state contracts must be designed before source migration.
- Media helpers need an adapter-local security and provenance review.

## Phase 2 recommendations

After human approval of the Core abstraction:

1. Define serialization functions for every Core model and freeze protocol fixtures.
2. Add a small API-key principal model with separate capability and authorization
   checks; initial scopes should include `events:read`, `commands:send`,
   `adapters:read`, `adapters:manage`, and `hardware:control`.
3. Implement health, adapter, endpoint, capability, command, and event endpoints
   against Core interfaces only.
4. Connect WebSocket subscriptions through Router destinations and test disconnect
   cleanup, heartbeat, filters, and reserved cursors.
5. Add an automated Fake IM loop: emit event, receive WebSocket event, submit HTTP
   command, and assert the fake adapter recorded it.
6. Keep API/server dependencies outside `gateway.core` and do not start Phase 3
   until the Phase 2 loop is deterministic.

## Five acceptance answers

1. Can Core run after all AstrBot Agent/LLM code is removed? **YES.**
2. Can Core start without Telegram/QQ/Weixin SDKs? **YES.**
3. Can a new Adapter be added without modifying Core? **YES**, through the adapter
   contract, registry factory, and `agent_gateway.adapters` entry point.
4. Can Fake Robot and Fake Sensor naturally use Event/Command? **YES**, covered by
   an automated sensor-event and robot-command flow.
5. Does Core retain a required chatbot assumption? **NO.** IM is only one payload
   profile and fake adapter beside sensor and robot transports.

# AstrBot Transport Extraction Audit

## Scope and baseline

This Phase 0 audit identifies the transport behavior that may be migrated from
AstrBot without retaining its agent runtime. It covers the platform abstraction,
message model, event bus, manager lifecycle, media, configuration, storage, API,
and extension coupling, with deeper inspection of OneBot v11, Telegram, and
Weixin OC.

- AstrBot version: `4.27.4`
- Upstream revision: `0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d`
- Audit date: 2026-08-31
- Source license: AGPL-3.0-or-later
- Result: no real adapter source is copied in Phase 1

## Current dependency graph

```text
CoreLifecycle
├── AstrBotConfig / AstrBotConfigManager
├── ProviderManager / ConversationManager / PluginManager / other AI services
├── PlatformManager
│   ├── hard-coded platform source imports
│   ├── platform_cls_map decorator registry
│   ├── Star handler registry and OnPlatformLoadedEvent hooks
│   ├── WebChatAdapter created unconditionally
│   └── Platform instances
│       ├── platform SDK/client
│       ├── AstrBotMessage + MessageSesion + MessageChain
│       ├── AstrMessageEvent
│       └── shared queue
└── EventBus
    ├── AstrBotConfigManager origin lookup
    └── PipelineScheduler per configuration
        └── plugin/agent pipeline stages
```

This graph has two boundary violations that prevent a lightweight runtime:

1. Transport input becomes an `AstrMessageEvent`, which already carries agent,
   provider, conversation, result, metric, and trace behavior.
2. The event bus has no neutral subscriber contract. Its only destination is a
   `PipelineScheduler` chosen through AstrBot configuration.

## Module classification

| Area | Current source | Decision | Reason |
|---|---|---|---|
| Platform SDK clients | `astrbot/core/platform/sources/*` | KEEP selectively | Protocol calls, reconnect, authentication, and transport parsing are valuable. |
| Platform-specific conversion | source adapter/event files | ADAPT | Convert SDK objects directly to `GatewayEvent`/`Payload`, and `GatewayCommand` directly to SDK operations. |
| `Platform` base | `astrbot/core/platform/platform.py` | REWRITE | Assumes `MessageSesion`, `MessageChain`, `AstrBotMessage`, metrics, and IM send semantics. |
| `PlatformManager` | `astrbot/core/platform/manager.py` | REWRITE | Reads AstrBot config, hard-codes imports, creates WebChat, and invokes Star plugin hooks. |
| Registration decorators | `astrbot/core/platform/register.py` | DROP | Replace global decorator map with standard Python entry points and a narrow registry. |
| `AstrBotMessage` | `astrbot/core/platform/astrbot_message.py` | DROP | Encodes sender/group/chat concepts and AstrBot message components. |
| `AstrMessageEvent` | `astrbot/core/platform/astr_message_event.py` | DROP | Imports `ToolSet`, `Conversation`, `ProviderRequest`, results, metrics, and traces; also owns send and LLM-request behavior. |
| Event bus | `astrbot/core/event_bus.py` | REWRITE | Directly targets `PipelineScheduler` and resolves AstrBot configuration origins. |
| Pipeline | `astrbot/core/pipeline/*` | DROP | Agent/plugin processing is outside the transport boundary. |
| Message components | `astrbot/core/message/components.py` | ADAPT as profiles | Preserve useful segment semantics in `im.message.v1`, not as Core unions. |
| Media helpers | `astrbot/core/utils/media_utils.py`, `io.py` | ADAPT selectively | Transport-safe download/resolve code may move to adapter-support packages after security review. |
| Configuration | `astrbot/core/config/*` | REWRITE | Gateway needs a small schema and secret references, not AstrBot's complete configuration object. |
| Storage | AstrBot DB/config persistence | REWRITE | Only adapter state, route state, dedup, and delivery state are allowed. No conversation or AI tables. |
| Dashboard/Open API | `astrbot/dashboard/*` | DROP for MVP | Phase 2 will expose a new REST/WebSocket contract; ChatUI is not migrated. |
| Star plugin system | `astrbot/core/star/*` | DROP | Adapter entry points are the only extension mechanism. |
| Core lifecycle | `astrbot/core/core_lifecycle.py` | DROP | It initializes provider, plugin, pipeline, knowledge, cron, and agent services together. |

## Platform abstraction and lifecycle findings

`Platform.run()` returns a long-running coroutine while `PlatformManager` creates
both a run task and a wrapper task. The wrapper changes a four-state status and
captures exceptions. Termination first calls the adapter, then cancels both tasks.
This is useful lifecycle intent, but the implementation is coupled to global
configuration, a shared IM event queue, WebChat, and plugin hooks.

Gateway should retain these behavioral lessons:

- one configured instance has an independent state and error record;
- one failed instance must not terminate siblings;
- stop is awaited before task cancellation or process shutdown;
- adapter context exposes only emit, logger, and secret resolution;
- discovery imports only installed adapter entry points.

Gateway must not retain:

- a hard-coded `match` statement for platform types;
- implicit WebChat startup;
- arbitrary `OnPlatformLoadedEvent` hooks;
- the AstrBot root configuration object in an adapter;
- a manager-owned path from transport input to an agent pipeline.

## Message and event model findings

`AstrBotMessage` assumes a sender, optional group, chat message type, session ID,
message ID, and a list of AstrBot message components. This is usable source
material for an IM profile but cannot be the Core event model.

`AstrMessageEvent` is specifically unsuitable for extraction. Its imports and
methods include:

- `ToolSet`;
- database `Conversation`;
- `ProviderRequest`;
- `MessageEventResult` and pipeline stop/continue state;
- LLM request construction;
- admin/wake-up/chat predicates;
- metrics and trace spans;
- platform-specific send, reaction, group, and streaming operations.

The replacement boundary is data-only:

```text
SDK event -> adapter parser -> GatewayEvent(Payload)
GatewayCommand -> adapter executor -> SDK operation -> CommandResult
```

IM sender, conversation, reply, and segments live only in `im.message.v1` data.
Sensor and robot payloads pass through the same Core without those fields.

## Event bus findings

The existing bus consumes an unbounded queue, looks up configuration by
`unified_msg_origin`, selects a `PipelineScheduler`, and launches one task for
each message. It cannot dispatch to an external consumer without the AstrBot
pipeline and config manager.

The replacement must therefore be new code. Phase 1 implements a bounded memory
queue, awaited publication for backpressure, neutral async subscribers, subscriber
exception isolation, and drain-before-stop semantics. Kafka, NATS, Redis, and
durability are intentionally absent.

## OneBot v11 dependency audit

Primary sources:

- `astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py`
- `astrbot/core/platform/sources/aiocqhttp/aiocqhttp_message_event.py`

### Transport dependencies to retain or adapt

- `aiocqhttp.CQHttp`, OneBot `Event`, `ActionFailed`;
- reverse WebSocket host, port, token, connection lifecycle, and reconnect behavior;
- OneBot request, notice, group, and private callbacks;
- OneBot segment parsing and `call_action` operations;
- reply lookup, member lookup, file URL lookup, media send, and message IDs;
- connection shutdown for reverse WebSocket clients.

### AstrBot coupling to remove

- inheritance from `Platform`;
- `AstrBotMessage`, `AstrMessageEvent`, `MessageSesion`, `MessageType`;
- wildcard AstrBot message components and `MessageChain`;
- decorator registration and global platform map;
- direct queue commit and AstrBot metrics;
- configuration names that leak AstrBot rather than an adapter-owned schema.

### Migration risk

OneBot segment conversion currently combines protocol parsing with AstrBot component
construction and performs network lookups while parsing replies, mentions, and
files. The port should first define explicit OneBot-to-IM-profile conversion tests.
Unknown segments must become `raw` instead of being silently ignored. Reverse
WebSocket shutdown relies on private `aiocqhttp` attributes and needs a versioned
compatibility test.

## Telegram dependency audit

Primary sources:

- `astrbot/core/platform/sources/telegram/tg_adapter.py`
- `astrbot/core/platform/sources/telegram/tg_event.py`

### Transport dependencies to retain or adapt

- `python-telegram-bot` application, polling, handlers, updates, bot client, and
  Telegram errors;
- chat type, media group collection, reply metadata, message/file download;
- text length splitting, media/file/audio send, reactions, edits, and typing;
- invalid-token, forbidden, network error, shutdown, and polling recovery behavior;
- Telegram message IDs and endpoint-specific capabilities.

### AstrBot coupling to remove

- `Platform`, `AstrBotMessage`, `AstrMessageEvent`, `MessageSesion`;
- AstrBot `MessageChain` and message components;
- Star command handler registries, command filters, and command-group filters;
- APScheduler job used to rebuild commands from plugin state;
- AstrBot temp paths, media resolver, metrics, and direct event queue commit;
- streaming behavior coupled to agent output generators.

### Migration risk

Command-menu registration is currently derived from the Star plugin registry and
must not be ported. Telegram's send implementation contains useful transport
behavior mixed with AstrBot streaming conventions; only platform operations and
segment conversion should move. Media-group timing and file lifecycle need isolated
adapter tests. The Telegram SDK remains an adapter-package dependency only.

## Weixin OC dependency audit

Primary sources:

- `astrbot/core/platform/sources/weixin_oc/weixin_oc_adapter.py`
- `astrbot/core/platform/sources/weixin_oc/weixin_oc_client.py`
- `astrbot/core/platform/sources/weixin_oc/weixin_oc_event.py`
- `astrbot/core/platform/sources/weixin_oc/login_registration.py`

### Transport dependencies to retain or adapt

- `aiohttp` request lifecycle and long polling;
- QR session creation, polling, expiry, confirmation, and account identifiers;
- AES media encryption/decryption and CDN upload/download;
- context tokens, update cursor, login token, and session persistence;
- typing tickets, media conversion, reply reconstruction, send operations;
- QR rendering as optional adapter/CLI support.

### AstrBot coupling to remove

- `Platform`, `AstrBotMessage`, `AstrMessageEvent`, `MessageSesion`;
- AstrBot message components and `MessageChain`;
- global `astrbot_config` mutation and AstrBot temp paths;
- AstrBot media resolver utilities without extraction and security review;
- event classes that retain the whole platform instance to send replies;
- stats structure inherited from AstrBot's platform dashboard.

### Migration risk

The adapter is substantially larger than OneBot or Telegram and combines login,
account persistence, long polling, media crypto, reply caches, typing sessions,
and message conversion. Persistent values include credentials and session tokens;
the Gateway storage boundary must store secret references or encrypted state rather
than copy AstrBot configuration behavior. Login state needs its own contract before
Phase 5. The client module is the cleanest candidate for selective extraction, but
it still logs through AstrBot and must receive a scoped logger.

## Dependency ownership summary

| Dependency | Owner after extraction | Core allowed? |
|---|---|---|
| Python stdlib (`asyncio`, `logging`, `dataclasses`, `importlib.metadata`) | Core | Yes |
| `aiocqhttp` | OneBot adapter package | No |
| `python-telegram-bot`, `telegramify-markdown` | Telegram adapter package | No |
| `aiohttp`, AES implementation, QR renderer | Weixin adapter package | No |
| AstrBot message/component models | Not migrated; converted at adapter boundary | No |
| AstrBot config/database/dashboard | Replaced by Gateway-specific packages | No |
| AI SDKs, MCP, RAG, provider and agent modules | Not part of Gateway | No |

## Phase 0 acceptance answers

### Which modules does OneBot currently depend on?

It directly depends on `aiocqhttp`, AstrBot API logging, platform/event/message
component APIs, `MessageSesion`, platform registration, and the shared event queue.
Through those abstractions it reaches metrics and the pipeline event model.

### Which modules does Telegram currently depend on?

It directly depends on `python-telegram-bot`, APScheduler, Telegram markdown support,
AstrBot logging, platform/event/message APIs, Star command registries and filters,
temp/media helpers, metrics, and the shared event queue.

### Which modules does Weixin currently depend on?

It directly depends on `aiohttp`, AES crypto, QR rendering, AstrBot logging,
configuration, platform/event/message APIs, temp/media helpers, account-state file
persistence, and the shared event queue.

### Which dependencies are transport responsibilities?

Protocol clients, authentication, login and QR state, polling/WebSocket lifecycle,
reconnect, protocol parsing, media encoding/transfer, send operations, external IDs,
and platform-specific capabilities belong to adapters.

### Which dependencies are Agent or Plugin responsibilities?

Provider requests, tool sets, conversations, prompt/LLM execution, pipeline results,
wake-up/admin decisions, plugin hooks and command registries, Star context, knowledge,
metrics tied to AI execution, and ChatUI do not belong to Gateway transport.

## Phase 0 conclusion

No existing AstrBot base event, platform manager, event bus, or lifecycle can be
used as Gateway Core without preserving forbidden dependencies. Selective real
adapter migration remains viable only when protocol logic is placed behind the new
`TransportAdapter` contract and every AstrBot-specific glue object is replaced.

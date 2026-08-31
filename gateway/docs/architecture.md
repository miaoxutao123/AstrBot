# Gateway Core Architecture

## Purpose

Gateway Core is a dependency-free transport kernel. It accepts observations from
adapter instances, distributes neutral events, validates commands against declared
capabilities, and delegates execution back to the addressed adapter. It neither
knows nor cares whether a consumer is an AI agent.

The optional Gateway API translates HTTP/WebSocket traffic into the Core models.
It contains authentication and wire concerns without making Core depend on
FastAPI. Generic media/state backends are host services; real platform SDKs, MCP,
and agent behavior are not part of Core.

## Dependency direction

```text
fake/real adapter ──implements──> TransportAdapter
        │                              │
        └── emits GatewayEvent ──> AdapterContext ──> MemoryEventBus

HTTP command ──> Gateway API ──> AdapterRuntime ──> GatewayCommand ──> adapter

MemoryEventBus ──> EventStream ──> filtered WebSocket clients

Router ──subscribes to──> MemoryEventBus
```

Allowed imports:

```text
adapter package -> gateway.core
gateway.api      -> gateway.core
future MCP       -> Gateway HTTP API/SDK
```

Forbidden imports:

```text
gateway.core -> concrete adapter
gateway.core -> platform SDK
gateway.core -> MCP
gateway.core -> AstrBot
gateway.core -> agent/LLM/provider/prompt/tool/memory modules
```

## Core components

### Models

`EndpointRef` is the only addressing primitive. Core does not define user, group,
friend, chat, topic, sensor, or robot subclasses. Adapters own endpoint syntax.

`Payload` is an open envelope with a versioned `schema` and opaque `data`. Core
does not implement a giant payload union.

`GatewayEvent` and `GatewayCommand` contain stable IDs, endpoint references,
adapter-defined types, payloads, metadata, and optional correlation IDs.

`Capability` is queryable at adapter or endpoint scope. In Phase 1 command type
must exactly match a declared capability name; unsupported commands fail explicitly.

### Adapter contract

`TransportAdapter` has five operations: descriptor, start, stop, execute, and
capabilities. `AdapterContext` exposes event emission, a scoped logger, secret
lookup, an adapter-namespaced state view, generic media storage, and health
reporting. It rejects events that claim another configured adapter ID and never
exposes the runtime, configuration manager, or a database connection.

`AdapterDescriptor.id` identifies an installed adapter type such as `telegram`.
`EndpointRef.adapter_id` identifies a configured instance such as `telegram-main`.
The distinction permits multiple accounts using one implementation.

### Registry

`AdapterRegistry` keeps adapter factories separate from configured instances.
Factories use this contract:

```python
def factory(instance_id: str, config: Mapping[str, Any]) -> TransportAdapter:
    ...
```

Installed adapters are discovered only through the standard
`astrbot_gateway.adapters` entry-point group. Core contains no platform import switch
and permits no arbitrary hook registration. Discovery is isolated per entry point:
the result records `loaded`, `failed`, and safe `errors`, so a broken third-party
package cannot prevent later adapters from being discovered.

### Runtime

`AdapterRuntime` owns instance states:

```text
STOPPED -> STARTING -> RUNNING
                      DEGRADED
             failure -> FAILED
RUNNING -> STOPPING -> STOPPED
```

Startup and shutdown exceptions are converted to safe errors and contained per
instance. `start_all` and `stop_all` run concurrently. A command is dispatched only
when the target adapter is running or degraded and declares the exact capability.
Adapter exceptions become `TRANSPORT_ERROR` results rather than leaking tracebacks.

`TransportAdapter.start(context)` is initialization, not a run-forever coroutine.
It creates background receive/reconnect tasks, establishes enough transport state
to accept work, and then returns. `stop()` cancels and awaits those tasks before it
returns. Background tasks report disconnect, recovery, and terminal failure through
the minimal `context.report_state(RUNNING|DEGRADED|FAILED, reason)` contract. Runtime
owns the transitional `STARTING`, `STOPPING`, and `STOPPED` states. Commands remain
available while degraded, allowing adapters to model temporary reconnect periods;
failed adapters reject commands as offline.

### Memory event bus

`MemoryEventBus` uses a bounded `asyncio.Queue`. Publication awaits free capacity,
which supplies backpressure. One subscriber exception is logged and does not block
other subscribers. Shutdown rejects new events, drains queued work, sends a private
sentinel, and awaits the dispatcher task.

Event admission and shutdown use a lock barrier. A publisher holds admission until
its queue insertion completes; shutdown closes admission only after all previously
admitted publishers have enqueued. Therefore the stop sentinel cannot overtake an
accepted event, including when publication was blocked by a full queue.

Core provides at-most-once in-memory delivery. The API adds best-effort replay from
its bounded process-local history; durable delivery and replay across restarts are
explicitly deferred.

### Router

`Router` matches only `transport`, `adapter_id`, and `event_type`, each optionally a
wildcard. It never inspects payload text or invokes intelligence. Destinations are
async callables for configured transport delivery. The Phase 2 WebSocket event
stream subscribes directly to the bus because every client applies its own filter.

### Lifecycle

`GatewayLifecycle` starts the event bus before adapters and stops adapters before
draining the bus. This ordering prevents adapters from emitting into a stopped bus
and preserves already accepted events during graceful shutdown.

### HTTP and WebSocket API

`create_app` binds a configured runtime and event bus to a FastAPI application.
Its ASGI lifespan subscribes the API event stream before adapter startup, then
stops adapters, drains the bus, and removes the subscription during shutdown.

The API layer owns explicit Core-to-wire serialization, request validation,
API-key scopes, stable HTTP errors, and adapter lifecycle endpoints. Unexpected
exceptions are logged server-side and become a generic `INTERNAL_ERROR`; Python
tracebacks and exception messages never enter the response.

`EventStream` is a bounded, in-memory delivery view. It deduplicates retained
events by stable ID, records endpoints observed in events, keeps a small replay
window, and creates a bounded queue per WebSocket client. A slow client is closed
explicitly instead of allowing unbounded memory growth. Filters use only transport,
adapter ID, and event type.

### Profiles, media, and adapter state

`gateway.profiles.im` is an optional layer above Core. It defines
`im.message.v1`, `im.message.outbound.v1`, conversation/sender models, the standard
segment vocabulary, and operation-level IM capabilities. Core imports neither this
profile nor any OneBot module.

Media bytes cross the network and adapter boundaries only through opaque
`media_id` metadata. `MemoryMediaStore` and `FileMediaStore` enforce upload size,
MIME syntax, safe filenames, random IDs, TTL, and deletion. The file store keeps a
persistent metadata index but never returns a local absolute path through the API.

`AdapterStateStore` persists only JSON-compatible adapter state. Runtime creates a
`NamespacedStateStore` for each configured instance, so an adapter sees local keys
while the host writes `adapter/<adapter_id>/...`. The first backends are memory and
SQLite; neither contains conversations, prompts, agent memory, or provider data.

### Standalone host

The YAML loader validates duplicate IDs, server/media/state bounds, adapter-owned
configuration, and environment-only secret references. `astrbot-gateway check`
discovers and instantiates adapter factories to validate Adapter API compatibility
without starting a platform connection. The `run` command composes storage,
registry, runtime, API keys, FastAPI, and Uvicorn.

OneBot is loaded through the `astrbot_gateway.adapters` entry-point group. Its
optional SDK imports stay inside the adapter client. Forward WebSocket mode owns a
reconnect loop and action/echo correlation; reverse mode preserves the compatible
aiocqhttp server lifecycle. Both convert directly between OneBot protocol data and
Gateway contracts.

Telegram uses the same entry-point boundary and imports `python-telegram-bot` only
inside its client. Polling and health probes report disconnect/recovery through the
shared runtime state contract. Telegram-specific chat and topic fields remain in
adapter-owned endpoint IDs while the standard IM profile preserves private, group,
channel, and thread conversation types.

## Non-IM proof

Phase 1 includes three contract-equivalent fake adapters:

- Fake IM emits `im.message.v1` and accepts IM send capabilities.
- Fake Sensor emits `sensor.temperature.v1` telemetry.
- Fake Robot emits `robot.pose.v1` and accepts move/stop/pose commands.

The sensor-to-event-bus and command-to-robot flow uses no chat fields and requires
no Core conditionals. This is the primary Phase 1 abstraction acceptance test.

## Security boundary

Capability describes what an endpoint can do; it is not authorization.
`AdapterContext` restricts host access, validates source adapter identity, and
avoids passing configuration/runtime/database objects into adapters. The network
boundary authenticates API keys and separately checks `events:read`,
`commands:send`, `adapters:read`, `adapters:manage`, and `hardware:control`.
Media routes additionally require `media:read` or `media:write`. Robot and hardware
transports require both command and hardware scopes.

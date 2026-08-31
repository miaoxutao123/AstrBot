# Gateway Core Architecture

## Purpose

Gateway Core is a dependency-free transport kernel. It accepts observations from
adapter instances, distributes neutral events, validates commands against declared
capabilities, and delegates execution back to the addressed adapter. It neither
knows nor cares whether a consumer is an AI agent.

Phase 1 intentionally contains no HTTP server, WebSocket server, storage backend,
real platform SDK, MCP package, or agent behavior.

## Dependency direction

```text
fake/real adapter ──implements──> TransportAdapter
        │                              │
        └── emits GatewayEvent ──> AdapterContext ──> MemoryEventBus

external API (Phase 2) ──> AdapterRuntime ──> GatewayCommand ──> adapter

Router ──subscribes to──> MemoryEventBus
```

Allowed imports:

```text
adapter package -> gateway.core
future API       -> gateway.core
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
capabilities. `AdapterContext` exposes only event emission, a scoped logger, and
secret lookup. It rejects events that claim another configured adapter ID.

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
`agent_gateway.adapters` entry-point group. Core contains no platform import switch
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

Phase 1 provides at-most-once in-memory delivery. Durability and disconnected-client
replay are explicitly deferred.

### Router

`Router` matches only `transport`, `adapter_id`, and `event_type`, each optionally a
wildcard. It never inspects payload text or invokes intelligence. Destinations are
async callables that will later include WebSocket and webhook delivery services.

### Lifecycle

`GatewayLifecycle` starts the event bus before adapters and stops adapters before
draining the bus. This ordering prevents adapters from emitting into a stopped bus
and preserves already accepted events during graceful shutdown.

## Non-IM proof

Phase 1 includes three contract-equivalent fake adapters:

- Fake IM emits `im.message.v1` and accepts IM send capabilities.
- Fake Sensor emits `sensor.temperature.v1` telemetry.
- Fake Robot emits `robot.pose.v1` and accepts move/stop/pose commands.

The sensor-to-event-bus and command-to-robot flow uses no chat fields and requires
no Core conditionals. This is the primary Phase 1 abstraction acceptance test.

## Security boundary in Phase 1

Capability describes what an endpoint can do; it is not authorization. Phase 1
does not expose a network API and therefore does not yet implement API keys or
scopes. `AdapterContext` restricts host access, validates source adapter identity,
and avoids passing configuration/runtime/database objects into adapters. Phase 2
must add caller scopes before commands become remotely accessible.

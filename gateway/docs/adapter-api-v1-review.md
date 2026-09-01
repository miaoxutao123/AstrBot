# Adapter API v1 Pre-freeze Review

Status: **HISTORICAL / SUPERSEDED**. This P5.1 review records the contract after
OneBot, Telegram, and Weixin. Phase 6 subsequently completed the Satori and QQ
Official pressure tests and froze Adapter API v1; the current decision is in
`adapter-api-v1-final-review.md`.

## Contract review

| Contract | Owner and callers | Neutral / hardware-friendly | Host boundary | Optional adapters | MQTT / ROS2 fit | Platform leakage |
| --- | --- | --- | --- | --- | --- | --- |
| `TransportAdapter` | Gateway Core owns it; Runtime calls lifecycle/execute/capability/auth methods; adapter authors implement it | Yes; lifecycle and commands do not assume chat | Receives only `AdapterContext`, not Runtime/config/database objects | Entry-point factories allow optional packages | Natural: polling/subscription tasks start in the background and commands remain typed payloads | None; interactive auth defaults to `NOT_REQUIRED` |
| `AdapterContext` | Runtime constructs it; one adapter instance consumes it | Yes; event emission, state, secrets, media, logs and health apply to devices and buses | Narrow facade; source identity and namespace are enforced by host | Every adapter gets the same services without importing host internals | MQTT cursors and ROS2 connection state fit naturally | None; `get_secret` is static host configuration, `secrets` is dynamic credential persistence |
| `AdapterDescriptor` | Adapter implements; registry/runtime/API read it | Yes; `family`, `adapter_type`, capabilities are generic | Immutable metadata only | Discovery validates API version per optional factory | Can describe `iot/mqtt` and `robotics/ros2` | None |
| `EndpointRef` | Core owns; adapters create sources, callers target commands | Yes; all four fields are opaque structural identity | No adapter or host objects exposed | Multiple types and instances coexist | Direct fit for topics, device IDs and ROS graph paths | None; identity never depends on `metadata.platform` |
| `GatewayEvent` | Core owns; adapters publish, subscribers/API consume | Yes; opaque type, payload schema and metadata | No agent/session/config reference | Unknown payload schemas pass through | Telemetry and robot state are first-class | None |
| `GatewayCommand` | Core owns; API/host creates, Runtime routes, adapter executes | Yes; target/type/payload are generic | Authorization stays at host/API boundary | Unsupported operations return stable errors | Natural command envelope for publish/service/action operations | None |
| `Capability` | Core owns vocabulary shape; profiles/adapters define names | Yes; not restricted to IM | Describes support, never authorization | Adapter and endpoint scopes may differ | MQTT publish/subscribe or robot motion capabilities fit | None |
| `MediaStore` | Gateway media layer owns; API and adapters call it | Mostly; useful to cameras/files as well as IM | Opaque IDs prevent filesystem-path leakage | Adapters need not use media | Binary sensor/camera payloads fit | None, but v1 reads and writes complete `bytes` |
| `AdapterStateStore` | Gateway state layer owns; adapters call namespaced view | Yes; JSON state suits cursors, offsets and device metadata | Backend hidden and namespace enforced | Optional adapters share no state keys | Natural for MQTT offsets and ROS2 reconnect metadata | None |
| `AdapterSecretStore` | Gateway secrets layer owns; adapters call namespaced view | Yes; string credentials cover tokens, keys and serialized device credentials | Backend/master key hidden and namespace enforced | Adapters may ignore it | Natural for broker credentials and device certificates serialized by adapter | None |
| Interactive auth | Core owns generic status/challenge models; Runtime/API delegate; adapters may override | Yes; default `NOT_REQUIRED`, device code and pairing instructions are generic | API exposes safe challenge data, never tokens | Entire implementation is optional | OAuth device flow and BLE pairing can use code/instructions; protocol-specific work stays in adapter | No Weixin fields; only `qr_uri`, `media_id`, `verification_code`, `instructions` |

## Decisions and known limits

- The default interactive-auth result `NOT_REQUIRED` is sufficient for the
  majority of adapters. QR, OAuth device flow and BLE-style pairing can be
  represented without adding platform names to Core. More elaborate browser
  redirects may pressure-test this in a later version.
- `MediaStore.get()` and `put()` materialize complete bytes. This is adequate for
  the bounded IM Gateway v1 media model but inefficient for very large files; a
  streaming interface is a potential v2 extension, not P5.1 work.
- The SQLite state backend uses one connection per operation, `asyncio.to_thread`,
  and a global async lock. This is acceptable for current correctness, namespace
  isolation and JSON compatibility. SQLAlchemy, aiosqlite, Redis and multi-process
  optimization are deliberately deferred.
- Secret values are non-empty strings. An adapter must serialize complex dynamic
  credentials itself. Persistent configuration fails explicitly on missing or
  invalid master keys and corrupted ciphertext; there is no plaintext fallback.
- `Adapter API v1` remains **NOT FROZEN** until Satori implementation and the
  resulting four-adapter contract review are complete.

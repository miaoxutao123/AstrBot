# Phase 6 Report — Protocol Validation and Adapter API v1 Freeze

## Baseline

Development started from `customization@43f51e458`, AstrBot-Gateway 0.5.1. Derived
protocol behavior remains pinned to AstrBot 4.27.4 commit
`0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d`.

## Identity hardening

`AdapterContext` now binds the descriptor family, adapter type and configured
adapter ID. Emitted events must match all three. `AdapterRuntimeInfo` and adapter
REST responses now expose `family`, `type`, and `id` independently.

## Satori implementation

Satori uses background WebSocket signaling, heartbeat/reconnect, HTTP operations,
sequence state and standard IM/media conversion. Multiple downstream platform and
bot logins are encoded in adapter-owned endpoint routing; Core still sees
`adapter_type=satori`.

## Satori feature matrix

| Feature | Status |
| --- | --- |
| Direct/channel receive and send | `INTEGRATION_PASS` |
| Text, mention, reply, image | `INTEGRATION_PASS` |
| Audio, video, file conversion | Implemented; real smoke pending |
| Unknown XML to raw | `INTEGRATION_PASS` |
| Multiple platform/account logins | `INTEGRATION_PASS` |
| Heartbeat, disconnect, reconnect, auth failure, shutdown | Simulated integration pass |

## QQ Official WebSocket implementation

The official Tencent transport obtains a dynamic access token, discovers the
Gateway, and supports IDENTIFY, heartbeat ACK, READY, RESUME, reconnect and invalid
session. C2C, group, guild/channel and direct events map to standard IM. Dynamic
credentials and resume metadata use SecretStore and StateStore respectively.

## QQ Official feature matrix

| Feature | Status |
| --- | --- |
| C2C/group/guild/direct receive | `INTEGRATION_PASS` |
| Text/reply send | `INTEGRATION_PASS` |
| C2C/group image upload | `INTEGRATION_PASS` |
| Guild/direct image send | Not implemented or advertised |
| Audio/video/file send | Not implemented or advertised |
| Unknown event/element to raw | `INTEGRATION_PASS` |
| Gateway discovery/lifecycle/resume/heartbeat timeout | Simulated integration pass |

## QQ Official vs OneBot distinction

QQ Official imports no OneBot code and shares only Gateway Core, IM Profile and
Media contracts. OneBot uses the OneBot v11 protocol; QQ Official uses Tencent App
credentials, official Gateway opcodes and official REST resources. Core has no
knowledge that both may reach QQ users.

## QQ Official Webhook shared-layer readiness

`qq_official/common` owns models, normalization, inbound/outbound conversion,
media, capabilities, errors and shared config. WebSocket owns only credentials,
Gateway signaling and transport composition. A webhook can call the same common
converters. QQ Official Webhook itself remains `NOT_STARTED`.

## Adapter API changes during P6

The only required contract hardening was complete event identity binding and the
addition of `family` to runtime status. No Satori/QQ/IM field or host Runtime
object was added. `GATEWAY_API_VERSION` remains 1 and
`GATEWAY_API_STABILITY` is now `stable`.

## Final five-adapter contract analysis

OneBot (bidirectional WS), Telegram (polling), Weixin (QR + long poll + encrypted
CDN), Satori (multi-platform WS/HTTP), and QQ Official (official WS/REST + resume)
all implement the same contract. Fake IM, Sensor and Robot continue to prove that
Core is not a chat kernel. The detailed decision is in
`docs/adapter-api-v1-final-review.md`.

## Tests

Local verification covers Core, API, shared contract, fake adapters, five real
adapter implementations, identity spoofing, secrets/state/media, architecture
guards, Satori closed loops and QQ Official gateway/REST closed loops. Ruff,
strict mypy and pyright pass alongside pytest.

## CI

Gateway CI runs Quality, Core, API, Adapter Contract, OneBot, Telegram, Weixin,
Satori and QQ Official jobs on Python 3.10 and 3.13. The final remote run is
evaluated after this report's commit is pushed.

## Real smoke status

- OneBot, Telegram, Weixin, Satori, QQ Official WebSocket:
  `INTEGRATION_PASS / REAL_SMOKE_PENDING`.
- No simulated result is labeled `REAL_SMOKE_PASS`.

## Known limitations

- Satori downstream feature support may vary by server/login; advertised
  capabilities describe this implementation rather than every backend.
- QQ Official audio/video/file send and guild/direct image upload are not claimed.
- MediaStore remains complete-bytes rather than streaming.
- Gateway queues and file/secret stores remain single-process facilities.
- Five authorized real environments were not available during automated work.

## Dependency changes

`aiohttp` and `websockets` are restricted to `satori`, `qq_official` and other
explicit extras/dev tooling. Base installation remains PyYAML plus pycryptodome.
The `astrbot_gateway.adapters` entry-point group now includes both adapters.

## Upstream provenance

Satori selectively rewrites the pinned `sources/satori` implementation. QQ
Official selectively rewrites `sources/qqofficial`, with local official Gateway
lifecycle and reusable common conversion. AstrBot Agent, MessageChain, plugins,
prompts, data paths and global runtime are removed; exact mappings are recorded in
`docs/upstream-map.md`.

## Freeze decision

**Adapter API v1: FROZEN**

Breaking changes to frozen methods, identity semantics, required Context services,
or entry-point naming require `GATEWAY_API_VERSION = 2`. Phase 7 was not started.

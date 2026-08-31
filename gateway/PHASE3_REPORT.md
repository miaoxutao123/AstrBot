# Phase 3 Report

## Implemented

- Fixed distribution naming as `astrbot-gateway` and adapter discovery as
  `astrbot_gateway.adapters`.
- Added the versioned IM profile, capability vocabulary, opaque media boundary,
  in-memory/file media stores, and authenticated media API.
- Added strict YAML configuration, environment-only secret references, offline
  config validation, CLI, and independently runnable Gateway Host.
- Added adapter-namespaced in-memory and SQLite state stores.
- Added a standalone OneBot v11 adapter for forward and reverse WebSocket modes,
  private/group inbound conversion, send/reply/delete, media, lifecycle health,
  reconnect, and invalid-token failure.
- Added an adapter migration matrix, per-adapter documentation, and a manual real
  smoke tool.

## Not implemented

- No Telegram, Weixin, Satori, other IM adapter, or MCP work was started.
- OneBot message editing, reactions, QQ administration, and AstrBot agent/plugin
  behavior are intentionally excluded.
- No real OneBot account/deployment was available for Phase 3 smoke execution.

## Architecture changes

- `profiles.im` is layered above transport-neutral Core; Core does not import it.
- `MediaStore` is the only byte boundary exposed to adapters and API callers.
  Adapter payloads contain opaque media IDs, never host paths.
- `AdapterStateStore` exposes only an adapter namespace, not database connections,
  runtime objects, or configuration managers.
- `GatewayHost` composes configuration, registry, runtime, state, media, and API.
- OneBot is loaded by package entry point and can be omitted without changing Core
  or the API.

## Adapter API changes

`AdapterContext` now exposes `state` and `media`. Runtime supplies a namespaced
state view to each adapter. Lifecycle semantics remain explicit: `start()` creates
background work and returns; state changes use the existing health reporter.

## Dependencies added

- Base: `PyYAML`
- API extra: `fastapi`, `python-multipart`, `uvicorn`
- OneBot extra: `aiohttp`, `aiocqhttp`
- Development/type checks: `httpx2`, `pytest`, `pytest-asyncio`, `ruff`, `mypy`,
  `pyright`, `types-PyYAML`

Optional SDKs are absent from the Core import graph.

## Tests

Automated coverage includes IM serialization, media validation/persistence/API,
state isolation/persistence, config and CLI, entry-point discovery, OneBot
fixtures, private/group text, mention, reply, image, file, unknown CQ raw fallback,
invalid token, unsupported command, disconnect/reconnect, forward loopback,
reverse aiocqhttp lifecycle, HTTP-to-OneBot action, OneBot-to-WebSocket event, and
clean shutdown. Existing Fake IM, Fake Robot, and Fake Sensor tests remain enabled.

CI splits quality, Core, API, generic adapter contract, and OneBot jobs across
Python 3.10 and 3.13. The final local test count and remote workflow result are
recorded in the implementing commit/CI run rather than hard-coded here.

## Real smoke status

`REAL_SMOKE_PENDING`. `scripts/smoke/onebot.py` is ready for an authorized real
deployment and prints `REAL_SMOKE_PASS` only after the required end-to-end actions
succeed. Simulated and loopback tests are reported only as `INTEGRATION_PASS`.

## Known issues

- Event replay is still bounded in-process delivery, not a durable queue.
- Real OneBot server variants can differ in media URL and reverse WebSocket details;
  these require real smoke confirmation.
- File media index updates are process-local serialized; a single file-store
  directory should be owned by one Gateway Host.

## Upstream provenance

OneBot behavior was selectively rewritten from
`astrbot/core/platform/sources/aiocqhttp/` in AstrBot `4.27.4`, commit
`0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d`, under AGPL-3.0-or-later. Exact files
and exclusions are recorded in `docs/upstream-map.md`. No AstrBot Agent runtime
type is imported by the adapter.

## Next-phase risks

- Telegram may require richer thread/channel and media-group semantics without
  weakening the neutral IM profile.
- Adapter contract freeze must account for health recovery and media/state behavior
  learned from the first real OneBot smoke.
- Phase 4 should begin only after human review and the six Phase 3 acceptance
  questions are confirmed.

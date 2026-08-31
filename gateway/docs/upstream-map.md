# AstrBot Upstream Provenance Map

## Baseline

- Repository: `AstrBotDevs/AstrBot`
- Version: `4.27.4`
- Commit: `0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d`
- Baseline date: 2026-08-31
- License: AGPL-3.0-or-later

Phase 1 Core and fake adapters are newly written. Phase 3 selectively rewrites the
OneBot transport behavior and records every derived package below.

| Gateway component | AstrBot source | Status | Local changes / plan |
|---|---|---|---|
| Core models | `astrbot/core/platform/astrbot_message.py`, `astr_message_event.py` (design input only) | New code | Replaced chat/agent model with Endpoint/Event/Command/Payload/Capability. No source copied. |
| Adapter contract | `astrbot/core/platform/platform.py` (lifecycle input only) | New code | Removed MessageChain, session, metrics, queue, and IM assumptions. |
| Adapter runtime | `astrbot/core/platform/manager.py` (behavioral input only) | New code | Replaced hard-coded imports and Star hooks with entry points and isolated state. |
| Memory event bus | `astrbot/core/event_bus.py` (behavioral input only) | New code | Replaced PipelineScheduler/config routing with neutral subscribers and bounded queue. |
| Fake IM | None | Test-only new code | Exercises `im.message.v1`. |
| Fake Sensor | None | Test-only new code | Exercises `sensor.temperature.v1`. |
| Fake Robot | None | Test-only new code | Exercises `robot.pose.v1` and robot commands. |
| `gateway/adapters/onebot/adapter.py` | `astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py` | Rewritten, 2026-08-31 | Replaced `Platform`, global registration, AstrBot events, and queue with `TransportAdapter`, entry point, Core events, state/media context, and isolated runtime health. Provenance header present. |
| `gateway/adapters/onebot/client.py` | `astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py` | Selective rewrite, 2026-08-31 | Retains reverse WebSocket lifecycle/action behavior and guarded private-client shutdown; adds forward WebSocket action/echo and bounded reconnect. No AstrBot imports. Provenance header present. |
| `gateway/adapters/onebot/inbound.py` | `astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py` | Rewritten, 2026-08-31 | Converts OneBot payloads directly to `im.message.v1`; unknown segments become `raw`; media becomes opaque `media_id`. Provenance header present. |
| `gateway/adapters/onebot/outbound.py` | `astrbot/core/platform/sources/aiocqhttp/aiocqhttp_message_event.py` | Rewritten, 2026-08-31 | Converts standard outbound IM segments to OneBot actions; removes `MessageChain`, streaming, local path exposure, and agent behavior. Provenance header present. |
| `gateway/adapters/onebot/config.py`, `capabilities.py`, `errors.py` | aiocqhttp package behavior and audited AstrBot adapter | New code, 2026-08-31 | Adapter-owned config, standard IM capability vocabulary, and isolated errors. |
| Telegram adapter | `astrbot/core/platform/sources/telegram/` | Not migrated | Planned Phase 4 selective port; Star command and agent streaming logic excluded. |
| Weixin adapter | `astrbot/core/platform/sources/weixin_oc/` | Not migrated | Planned Phase 5 selective port of client, login, state, media, polling, and send behavior. |

## Required migration record

For every future derived file, add a row containing:

```text
Gateway file/package
exact AstrBot source path
upstream version and full commit
migration date
license/provenance header status
removed AstrBot dependencies
local protocol and lifecycle changes
```

Do not perform automated upstream synchronization. Upstream changes must be reviewed
and ported deliberately against adapter contract and provenance tests.

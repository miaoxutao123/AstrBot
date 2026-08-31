# AstrBot Upstream Provenance Map

## Baseline

- Repository: `AstrBotDevs/AstrBot`
- Version: `4.27.4`
- Commit: `0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d`
- Baseline date: 2026-08-31
- License: AGPL-3.0-or-later

Phase 1 Core and fake adapters are newly written and do not copy a real AstrBot
adapter. The following table records audit sources and planned migration ownership.
It must be updated file-by-file when real adapter migration begins.

| Gateway component | AstrBot source | Status | Local changes / plan |
|---|---|---|---|
| Core models | `astrbot/core/platform/astrbot_message.py`, `astr_message_event.py` (design input only) | New code | Replaced chat/agent model with Endpoint/Event/Command/Payload/Capability. No source copied. |
| Adapter contract | `astrbot/core/platform/platform.py` (lifecycle input only) | New code | Removed MessageChain, session, metrics, queue, and IM assumptions. |
| Adapter runtime | `astrbot/core/platform/manager.py` (behavioral input only) | New code | Replaced hard-coded imports and Star hooks with entry points and isolated state. |
| Memory event bus | `astrbot/core/event_bus.py` (behavioral input only) | New code | Replaced PipelineScheduler/config routing with neutral subscribers and bounded queue. |
| Fake IM | None | Test-only new code | Exercises `im.message.v1`. |
| Fake Sensor | None | Test-only new code | Exercises `sensor.temperature.v1`. |
| Fake Robot | None | Test-only new code | Exercises `robot.pose.v1` and robot commands. |
| OneBot adapter | `astrbot/core/platform/sources/aiocqhttp/` | Not migrated | Planned Phase 3 selective port of protocol, parsing, send, media, reply, and reconnect. |
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

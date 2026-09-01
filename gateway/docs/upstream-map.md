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
| `gateway/adapters/telegram/adapter.py`, `client.py` | `astrbot/core/platform/sources/telegram/tg_adapter.py` | Selective rewrite, 2026-08-31 | Polling lifecycle, reconnect health, media-group debounce, entry-point loading, and state/media boundaries. AstrBot commands, scheduler, plugins, and event queue removed. Provenance headers present. |
| `gateway/adapters/telegram/inbound.py` | `astrbot/core/platform/sources/telegram/tg_adapter.py` | Rewritten, 2026-08-31 | Direct Bot API update to standard IM conversion for private/group/channel/thread, reply, entities, and media. No AstrBot message types. Provenance header present. |
| `gateway/adapters/telegram/outbound.py` | `astrbot/core/platform/sources/telegram/tg_event.py` | Rewritten, 2026-08-31 | Standard send/reply/edit/delete/reaction/typing operations and 4096-character splitting. MessageChain, Markdown rewriting, metrics, and Agent streaming removed. Provenance header present. |
| `gateway/adapters/telegram/config.py`, `capabilities.py`, `errors.py` | Telegram Bot API and audited AstrBot adapter | New code, 2026-08-31 | Environment-only token config, rich standard IM capability declarations, and safe error categories. |
| `gateway/adapters/weixin/adapter.py`, `client.py`, `auth.py`, `session.py`, `inbound.py`, `outbound.py`, `media.py` | `astrbot/core/platform/sources/weixin_oc/weixin_oc_adapter.py`, `weixin_oc_client.py`, `login_registration.py`, `weixin_oc_event.py` | Selective rewrite, 2026-08-31; responsibility split 2026-09-01 | Generic auth integration, separate namespaced state/secrets, opaque media, polling/reconnect and standard IM operations. Removed AstrBot config/data paths, MessageChain, platform events, plugins, prompts, and Agent runtime. Provenance headers present. |
| `gateway/adapters/weixin/config.py`, `capabilities.py`, `errors.py` | Weixin OC protocol and audited AstrBot adapter | New code, 2026-08-31 | Adapter-owned URLs/timing, standard IM capabilities, and safe error categories. |

## Unmigrated inventory

Every AstrBot Core message adapter still outside Gateway is listed here, even when
its migration phase has not yet been scheduled. The baseline for every row is
`AstrBot 4.27.4@0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d`.

| Adapter | AstrBot source path | Planned phase | Status |
| --- | --- | --- | --- |
| Satori | `astrbot/core/platform/sources/satori/` | P6 | `NOT_STARTED` |
| QQ Official WebSocket | `astrbot/core/platform/sources/qqofficial/` | Post-P6 | `NOT_STARTED` |
| QQ Official Webhook | `astrbot/core/platform/sources/qqofficial_webhook/` | Post-P6 | `NOT_STARTED` |
| Lark / Feishu | `astrbot/core/platform/sources/lark/` | Post-P6 | `NOT_STARTED` |
| DingTalk | `astrbot/core/platform/sources/dingtalk/` | Post-P6 | `NOT_STARTED` |
| WeCom Application | `astrbot/core/platform/sources/wecom/` | Post-P6 | `NOT_STARTED` |
| WeCom AI Bot | `astrbot/core/platform/sources/wecom_ai_bot/` | Post-P6 | `NOT_STARTED` |
| Weixin Official Account | `astrbot/core/platform/sources/weixin_official_account/` | Post-P6 | `NOT_STARTED` |
| Discord | `astrbot/core/platform/sources/discord/` | Post-P6 | `NOT_STARTED` |
| Slack | `astrbot/core/platform/sources/slack/` | Post-P6 | `NOT_STARTED` |
| LINE | `astrbot/core/platform/sources/line/` | Post-P6 | `NOT_STARTED` |
| KOOK | `astrbot/core/platform/sources/kook/` | Post-P6 | `NOT_STARTED` |
| Mattermost | `astrbot/core/platform/sources/mattermost/` | Post-P6 | `NOT_STARTED` |
| Misskey | `astrbot/core/platform/sources/misskey/` | Post-P6 | `NOT_STARTED` |
| WebChat | `astrbot/core/platform/sources/webchat/` | Never | `DROP` — internal UI/agent-facing chat surface |

Matrix and VoceChat are community-maintained plugins rather than Core packages;
they remain `COMMUNITY / FUTURE_PORT` and are tracked in the migration matrix.

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

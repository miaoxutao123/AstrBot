# Adapter Migration Matrix

This inventory is pinned to AstrBot `4.27.4` commit
`0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d`. `INTEGRATION_PASS` means only that
the deterministic Gateway suite passed; it never implies a real platform smoke
pass.

## AstrBot Core adapters

| Adapter | Source | Category | Target phase | Migration status | Automated coverage | Real smoke | Upstream baseline | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OneBot v11 | `astrbot/core/platform/sources/aiocqhttp/` | Core / protocol | P3 | `INTEGRATION_PASS` | Unit, contract, loopback WebSocket, mocked actions, API integration | `REAL_SMOKE_PENDING` | `4.27.4@0da69dd3` | Forward and reverse WebSocket modes |
| Telegram | `astrbot/core/platform/sources/telegram/` | Core / protocol | P4 | `INTEGRATION_PASS` | Unit, contract, mocked SDK lifecycle, API integration | `REAL_SMOKE_PENDING` | `4.27.4@0da69dd3` | Bot API polling |
| Weixin OC | `astrbot/core/platform/sources/weixin_oc/` | Core / protocol | P5 | `INTEGRATION_PASS` | QR auth, state/secret persistence, polling, send/media/typing, expiry, API integration | `REAL_SMOKE_PENDING` | `4.27.4@0da69dd3` | P5.1 internals split by responsibility |
| Satori | `astrbot/core/platform/sources/satori/` | Core / protocol | P6 | `INTEGRATION_PASS` | Lifecycle, multiple login, XML/media conversion, API integration | `REAL_SMOKE_PENDING` | `4.27.4@0da69dd3` | Multi-platform protocol pressure test |
| QQ Official WebSocket | `astrbot/core/platform/sources/qqofficial/` | Core / protocol | P6 | `INTEGRATION_PASS` | Gateway signaling, four message domains, media, errors, API integration | `REAL_SMOKE_PENDING` | `4.27.4@0da69dd3` | Tencent official transport, independent from OneBot |
| QQ Official Webhook | `astrbot/core/platform/sources/qqofficial_webhook/` | Core / protocol | Post-P6 | `NOT_STARTED` | None | Not run | `4.27.4@0da69dd3` | HTTP callback lifecycle |
| Lark / Feishu | `astrbot/core/platform/sources/lark/` | Core / protocol | Post-P6 | `NOT_STARTED` | None | Not run | `4.27.4@0da69dd3` | Includes callback server and app registration |
| DingTalk | `astrbot/core/platform/sources/dingtalk/` | Core / protocol | Post-P6 | `NOT_STARTED` | None | Not run | `4.27.4@0da69dd3` | App registration is adapter-owned |
| WeCom Application | `astrbot/core/platform/sources/wecom/` | Core / protocol | Post-P6 | `NOT_STARTED` | None | Not run | `4.27.4@0da69dd3` | Application/customer-service path |
| WeCom AI Bot | `astrbot/core/platform/sources/wecom_ai_bot/` | Core / protocol | Post-P6 | `NOT_STARTED` | None | Not run | `4.27.4@0da69dd3` | Long connection and webhook variants |
| Weixin Official Account | `astrbot/core/platform/sources/weixin_official_account/` | Core / protocol | Post-P6 | `NOT_STARTED` | None | Not run | `4.27.4@0da69dd3` | Not the Weixin OC transport |
| Discord | `astrbot/core/platform/sources/discord/` | Core / protocol | Post-P6 | `NOT_STARTED` | None | Not run | `4.27.4@0da69dd3` | SDK remains optional at migration time |
| Slack | `astrbot/core/platform/sources/slack/` | Core / protocol | Post-P6 | `NOT_STARTED` | None | Not run | `4.27.4@0da69dd3` | Client and event conversion |
| LINE | `astrbot/core/platform/sources/line/` | Core / protocol | Post-P6 | `NOT_STARTED` | None | Not run | `4.27.4@0da69dd3` | API and event conversion |
| KOOK | `astrbot/core/platform/sources/kook/` | Core / protocol | Post-P6 | `NOT_STARTED` | None | Not run | `4.27.4@0da69dd3` | Client/config/role behavior remains adapter-owned |
| Mattermost | `astrbot/core/platform/sources/mattermost/` | Core / protocol | Post-P6 | `NOT_STARTED` | None | Not run | `4.27.4@0da69dd3` | Client and event conversion |
| Misskey | `astrbot/core/platform/sources/misskey/` | Core / protocol | Post-P6 | `NOT_STARTED` | None | Not run | `4.27.4@0da69dd3` | API/utilities remain adapter-owned |
| WebChat | `astrbot/core/platform/sources/webchat/` | Core / internal surface | Never | `DROP` | Inventory only | Not applicable | `4.27.4@0da69dd3` | Internal UI/agent-facing chat surface; Gateway HTTP/WebSocket APIs replace this coupling role |

## Community adapters

These are separately maintained plugins referenced by AstrBot documentation and
are not AstrBot Core source packages.

| Adapter | Source | Category | Target phase | Migration status | Automated coverage | Real smoke | Upstream baseline | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Matrix | `stevessr/astrbot_plugin_matrix_adapter` | Community plugin | Future port | `COMMUNITY / FUTURE_PORT` | None | Not run | External repository | No Core source path in the pinned tree |
| VoceChat | `HikariFroya/astrbot_plugin_vocechat` | Community plugin | Future port | `COMMUNITY / FUTURE_PORT` | None | Not run | External repository | No Core source path in the pinned tree |

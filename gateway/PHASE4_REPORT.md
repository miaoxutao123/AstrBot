# Phase 4 Report

## Implemented

- Added a Telegram adapter loaded through `astrbot_gateway.adapters` with an
  optional `python-telegram-bot` dependency.
- Added Bot API polling lifecycle, bounded rebuild backoff, health recovery,
  terminal authentication failure, and clean SDK shutdown.
- Added private, group, channel, and forum-thread addressing without changing Core.
- Added inbound text/entity/reply/media/location conversion, opaque media storage,
  edited-message/reaction events, and bounded media-group collection.
- Added standard send/reply/edit/delete/reaction/typing operations, media sends,
  Telegram error mapping, and 4096-character text splitting.
- Added operation payload models for edit, delete, reaction, and typing.
- Added a protected real-environment smoke script and Telegram-specific CI group.

## Not implemented

- No Weixin, Satori, other adapter, or MCP work was started.
- Webhooks, Bot command registration, Telegram administration, payments, polls,
  Agent streaming/drafts, Markdown transformation, media editing, and atomic album
  sends are intentionally excluded.
- No authorized real Telegram bot/chat environment was available in this run.

## Architecture changes

The shared IM profile now defines small versioned payloads for edit, delete,
reaction, and typing. Core remains unchanged and imports neither the IM profile nor
Telegram. The adapter owns endpoint syntax, Bot API normalization, album buffering,
error translation, and SDK lifecycle. API continues to dispatch only generic
commands and events.

## Adapter API changes

No Adapter API change was required. Telegram uses the existing lifecycle health,
namespaced state, opaque media, event emission, and secret resolver services added
before the Phase 6 contract freeze.

## Dependencies added

- Telegram extra: `python-telegram-bot>=22.6,<23`

The base installation still imports Core and discovers adapter entry points without
importing the optional Telegram SDK.

## Tests

Automated coverage includes Telegram configuration, private/group/thread mapping,
UTF-16 entity offsets, reply, image/file ingestion, album merge, text splitting,
media send, send/edit/delete/reaction/typing actions, HTTP command integration,
WebSocket event delivery, invalid-token failure, network degradation/recovery,
unsupported commands, and clean shutdown.

CI has separate Quality, Core, API, adapter-contract, OneBot, and Telegram jobs on
Python 3.10 and 3.13. Local and remote totals are recorded with the implementing
commit rather than hard-coded in this report.

## Real smoke status

`REAL_SMOKE_PENDING`. `scripts/smoke/telegram.py` contains the complete protected
manual sequence and cannot print `REAL_SMOKE_PASS` without all required platform
operations and a real `DEGRADED -> RUNNING` reconnect transition.

## Known issues

- SDK file downloads can buffer bytes before the final Gateway limit check when
  Telegram omits declared file size.
- Album receive is ordered and merged, but outbound atomic albums are deferred.
- Telegram permissions, privacy settings, and allowed reaction sets vary by chat
  and require real-environment validation.

## Upstream provenance

Lifecycle and conversion behavior was selectively rewritten from
`astrbot/core/platform/sources/telegram/tg_adapter.py` and `tg_event.py` in AstrBot
`4.27.4`, commit `0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d`, under
AGPL-3.0-or-later. File-level mappings and removed Agent dependencies are recorded
in `docs/upstream-map.md` and module provenance headers.

## Next-phase risks

- A real Telegram smoke may reveal permission-specific error distinctions or Bot
  API server differences that should be fixed before the Adapter API freeze.
- Weixin login/session persistence will stress state ownership differently from a
  token-based polling adapter.
- Phase 5 must not introduce credential state or QR/login primitives into Core.

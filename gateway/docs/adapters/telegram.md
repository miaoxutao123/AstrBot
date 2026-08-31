# Telegram Adapter

## Source

Transport behavior was selectively rewritten from
`astrbot/core/platform/sources/telegram/tg_adapter.py` and `tg_event.py`. The
Gateway adapter does not import AstrBot's command registry, Star/plugins,
`AstrMessageEvent`, `AstrBotMessage`, `MessageChain`, metrics, prompts, providers,
or Agent streaming code.

## Upstream revision

- Repository: `AstrBotDevs/AstrBot`
- Version: `4.27.4`
- Commit: `0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d`
- Migration date: 2026-08-31

## Dependencies

Install `astrbot-gateway[telegram]` for `python-telegram-bot`. The SDK is lazily
imported inside the Telegram client and is absent from Core and API imports.

## Authentication

Create a bot with BotFather and store its token in an environment variable. YAML
must use an environment reference; literal tokens are rejected:

```yaml
token:
  env: TELEGRAM_BOT_TOKEN
```

Invalid tokens or polling authorization failures report terminal `FAILED`. Tokens are never placed in
events, errors, logs, state, or media metadata.

## Configuration

```yaml
- id: telegram-main
  type: telegram
  enabled: true
  config:
    token:
      env: TELEGRAM_BOT_TOKEN
    base_url: https://api.telegram.org/bot
    file_base_url: https://api.telegram.org/file/bot
    polling_timeout: 30
    reconnect_max_delay: 30
    health_interval: 15
    media_group_timeout: 1
    media_group_max_wait: 10
```

Custom HTTP(S) Bot API endpoints are supported. Webhook mode is not implemented.

## Feature matrix

| Feature | Receive | Send |
| --- | ---: | ---: |
| Private message | Yes | Yes |
| Group/supergroup message | Yes | Yes |
| Channel post | Yes | Yes |
| Forum topic/thread | Yes | Yes |
| Text | Yes | Yes, split at 4096 |
| Mention/text mention | Yes | Yes, plain `@name` |
| Reply | Yes | Yes |
| Image/photo | Yes | Yes |
| Audio/voice | Yes | Yes as voice |
| Video/video note | Yes | Yes as video |
| File/document | Yes | Yes |
| Location | Yes | Yes |
| Media group/album | Yes, merged | Individual media sends |
| Sticker | Yes as image/raw fallback | No |
| Edit | Yes as `im.message.edited` | Text edit |
| Delete | No Bot API update | Yes |
| Reaction | Yes | Add/remove |
| Typing/upload action | No inbound event | Yes |
| Unknown update/content | Preserved as Telegram event/raw | No |

## Receive capabilities

Bot API updates are normalized to mappings at the SDK boundary. Messages use
`im.message.v1`; edited messages reuse the profile with event type
`im.message.edited`; reaction updates use `im.reaction.event.v1`. Album items are
debounced with a hard maximum wait and emitted as one ordered IM event.

## Send capabilities

The adapter declares `im.message.send`, `im.message.reply`, `im.message.edit`,
`im.message.delete`, `im.reaction.add`, `im.reaction.remove`, and `im.typing.set`.
Image, audio, video, and file segments resolve only opaque `media_id` references.

## Unsupported features

Webhook hosting, Telegram command-menu registration, plugin command discovery,
Markdown conversion, Agent token streaming/drafts, media editing, album sends,
polls, payments, and administration APIs are outside Phase 4.

## Gateway mappings

- Private: `private:<chat_id>`
- Group/supergroup: `group:<chat_id>`
- Channel: `channel:<chat_id>`
- Forum topic: `thread:<chat_id>:<message_thread_id>`

Endpoint syntax remains adapter-owned and opaque to Core. Conversation types stay
private/group/channel/thread rather than being forced into a QQ-shaped model.

## Platform-specific capabilities

No `telegram.*` capability is required in Phase 4 because the implemented behavior
fits the standard IM vocabulary. Unknown Telegram updates remain observable as
`telegram.update` events without claiming a callable platform operation.

## Lifecycle and reconnect

`start()` creates polling work and returns. Initialization and active polling
report `RUNNING`; network failures report `DEGRADED`; health probes report recovery;
invalid credentials report `FAILED`. Unexpected polling exit rebuilds the SDK
application with bounded exponential backoff. `stop()` cancels album timers,
flushes collected items, stops polling, and shuts down SDK HTTP resources.

## Error mapping

- Invalid token / polling authorization failure: `AUTH_FAILED`, terminal state
- Bad request or chat-level forbidden operation: `INVALID_COMMAND`
- Network/timeout: retryable `TRANSPORT_ERROR` and `DEGRADED`
- RetryAfter: retryable `RATE_LIMITED` with `retry_after`

## Known limitations

- Telegram SDK download helpers buffer received files before the Gateway size check;
  the declared Telegram file size is checked first when available.
- Plain mention sends require a username-like display value and do not generate
  Markdown links for numeric user IDs.
- Album receive is supported, while atomic Telegram media-group sending is deferred.
- Bot API permissions and chat policies can reject otherwise valid operations.

## Test status

`INTEGRATION_PASS`: fixtures and automated tests cover private messages, group
threads, UTF-16 mention offsets, reply, image, file, media groups, long-text split,
API-to-Telegram send/edit/delete/reaction/typing, Telegram-to-WebSocket delivery,
invalid token, network degradation/recovery, unsupported commands, and shutdown.
Existing OneBot, Fake Robot, Fake Sensor, Core, and API suites remain enabled.

## Real smoke status

`REAL_SMOKE_PENDING`. Run the protected manual test only with an authorized bot:

```bash
python scripts/smoke/telegram.py \
  --private-chat-id <private-id> \
  --group-chat-id <group-id> \
  --image <image-path> \
  --file <file-path>
```

The script prints `REAL_SMOKE_PASS` only after real private/group receive, text,
image, file, reply, reaction, edit, typing, and forced connectivity recovery pass.

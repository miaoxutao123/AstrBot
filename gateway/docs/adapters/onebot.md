# OneBot v11 Adapter

## Source

The transport behavior was selectively rewritten from
`astrbot/core/platform/sources/aiocqhttp/`. The Gateway implementation does not
import AstrBot's Agent runtime, `AstrMessageEvent`, `MessageChain`, Pipeline, Star,
Plugin, Provider, or agent streaming code.

## Upstream revision

- Repository: `AstrBotDevs/AstrBot`
- Version: `4.27.4`
- Commit: `0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d`
- Migration date: 2026-08-31

## Dependencies

Install `astrbot-gateway[onebot]` for `aiocqhttp` and `aiohttp`. Forward WebSocket
mode uses `aiohttp`; reverse WebSocket mode uses `aiocqhttp`. Neither SDK is
imported by Core or the API layer.

## Authentication

The optional OneBot access token must be an environment reference in YAML:

```yaml
token:
  env: ONEBOT_ACCESS_TOKEN
```

Literal secrets are rejected. Forward mode sends the token as a Bearer credential.
An HTTP 401 or 403 WebSocket handshake is terminal and reports `FAILED`.

## Configuration

Forward WebSocket client:

```yaml
mode: websocket
endpoint: ws://127.0.0.1:3001
token:
  env: ONEBOT_ACCESS_TOKEN
action_timeout: 30
reconnect_max_delay: 30
```

Reverse WebSocket server:

```yaml
mode: reverse_websocket
host: 127.0.0.1
port: 6199
token:
  env: ONEBOT_ACCESS_TOKEN
```

## Feature matrix

| Feature | Receive | Send |
| --- | ---: | ---: |
| Private text | Yes | Yes |
| Group text | Yes | Yes |
| Mention / mention-all | Yes | Yes |
| Reply | Yes | Yes |
| Image | Yes | Yes |
| Audio | Yes | Yes |
| Video | Yes | Yes |
| File | Yes | Yes |
| JSON | Yes | Yes |
| Unknown CQ segment | Preserved as `raw` | OneBot `raw` only |
| Notice / request / meta event | Platform event | No |
| Delete message | N/A | Yes |
| Edit message | No | No |
| Reaction | No | No |

## Gateway mappings

- Private conversations map to `private:<user_id>` endpoints.
- Group conversations map to `group:<group_id>` endpoints.
- Received messages use `im.message.v1`.
- Sends and replies use `im.message.outbound.v1` with `im.message.send` or
  `im.message.reply`.
- Deletes use `im.message.delete`.
- Downloaded and uploaded files cross the adapter boundary only as opaque
  `media_id` values.
- OneBot message IDs remain external IDs and are retained for reply/delete.

Endpoint syntax is adapter-owned. Core treats every endpoint ID as opaque.

## Platform-specific capabilities

Transport-relevant OneBot notice, request, and meta events are exposed as
`onebot.notice`, `onebot.request`, and `onebot.meta_event`. No QQ administration API
is advertised in Phase 3.

## Lifecycle and reconnect

`start()` creates background receive work and returns. While awaiting a connection
the adapter is `DEGRADED`; a connected transport reports `RUNNING`. A non-terminal
disconnect reports `DEGRADED` and forward mode retries with bounded exponential
backoff. Invalid credentials report `FAILED`. `stop()` cancels receive/reconnect
work and closes the SDK/client without leaving a dispatcher task behind.

## Unsupported features

Message editing, reactions, QQ administration, AstrBot commands, plugins, providers,
LLM streaming, and agent metrics are not supported. Unsupported standard commands
fail explicitly rather than being translated to a guessed OneBot action.

## Known limitations

- Forward mode requires a OneBot v11 implementation supporting array message
  segments and action/echo responses.
- Media downloads are bounded, but remote URL behavior still depends on the OneBot
  implementation.
- Runtime state persists only the transport identifiers required for recovery; it
  is not a durable event queue.

## Test status

`INTEGRATION_PASS`: protocol fixtures, inbound/outbound conversion, invalid token,
disconnect/reconnect, unsupported command, shutdown, loopback forward WebSocket,
reverse aiocqhttp lifecycle, media API, WebSocket receive, and HTTP command paths
are automated. Fake Robot and Fake Sensor regression suites remain part of CI.

## Real smoke status

`REAL_SMOKE_PENDING`. Run `scripts/smoke/onebot.py` against an authorized real
OneBot deployment. Phase 3 does not claim `REAL_SMOKE_PASS` without private/group
receive, WebSocket delivery, text/image/reply send, and reconnect evidence.

```bash
python scripts/smoke/onebot.py \
  --private-id <qq-user-id> \
  --group-id <qq-group-id> \
  --image <local-smoke-image>
```

The script interactively waits for private/group input and then requires the real
OneBot peer to disconnect and recover. It never treats adapter mocks or a Gateway
WebSocket client reconnect as proof of a real OneBot reconnect.

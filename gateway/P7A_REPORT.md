# P7A Report — Runtime Hardening and Python SDK MVP

## Runtime fixes

QQ Official now invalidates a cached dynamic token on 401/403, removes its
SecretStore value, refreshes once using AppID/AppSecret, persists the new token,
and retries exactly once. A refresh failure is mapped to authentication failure.
Heartbeat work is supervised and retrieved; timeout closes the socket and enters
the normal `DEGRADED` reconnect path without detached-task exceptions.

Satori classifies WebSocket HTTP handshake 401/403 as terminal authentication
failure rather than reconnecting forever. Provider-specific authentication
rejection after an established signaling connection remains real-smoke work.

## SDK implemented API

`packages/python-sdk` contains `astrbot-gateway-sdk` and its single public
client, `AsyncGatewayClient`. It uses only HTTP and WebSocket wire protocol
dependencies, never Gateway Core or adapter imports.

- `health`, `list_adapters`, `list_endpoints`, `get_capabilities`
- reconnecting, filterable `events` with best-effort `last_event_id` replay
- `send_text`, event-aware `reply`, and `upload_media`
- lightweight event, endpoint, and standard IM message views while retaining raw
  wire data

## Closed-loop test

The SDK integration test starts a real local Gateway API with FakeIM, streams an
inbound event through the SDK, calls `reply`, and asserts the FakeIM receives an
`im.message.reply` command with the inbound message ID and correlation ID.

## Known limitations

- This MVP provides only `AsyncGatewayClient`; there is no synchronous client.
- Event replay is bounded by Gateway's in-memory retention and is best effort.
- The current stable Gateway wire event type for standard IM is `im.message`.
- No Webhook, MCP, WebUI, API-key CRUD, TypeScript SDK, or new adapter was
  started.

## CI status

Local Gateway and SDK verification is required before push. Gateway CI includes
a Python SDK matrix job on Python 3.10 and 3.13.

## Next batch recommendation

Run authorized real Satori and QQ Official smoke tests, then choose a separately
scoped Batch B. Do not start Webhook, MCP, or dashboard work implicitly.

# Weixin OC Adapter

## Source and boundary

Protocol behavior was selectively rewritten from AstrBot 4.27.4 commit
`0da69dd3f6b0e2a8e012ee3ce03cd4204e547e0d`, files
`astrbot/core/platform/sources/weixin_oc/`. The Gateway version imports no AstrBot
configuration, data directory, MessageChain, event, plugin, prompt, or Agent code.

Install with `astrbot-gateway[weixin]`. The extra contains `aiohttp`;
`pycryptodome` is a base dependency because it also provides the Gateway's
persistent encrypted secret backend. Both protocol clients remain outside Core.

## Configuration

```yaml
- id: weixin-main
  type: weixin
  enabled: true
  config:
    base_url: https://ilinkai.weixin.qq.com
    cdn_base_url: https://novac2c.cdn.weixin.qq.com/c2c
    qr_poll_interval: 1
    long_poll_timeout: 35
    api_timeout: 120
    reconnect_max_delay: 30
```

No token belongs in YAML. Account ID, polling cursor, and server-selected base URL
are ordinary metadata in the namespaced `AdapterStateStore`. The login token and
per-user context tokens are credentials in the separate namespaced
`AdapterSecretStore`. Configure `secrets.type: encrypted_file` and the environment
master key for recovery after restart; the default memory secret backend requires
re-login. A legacy pre-v1 state containing plaintext credentials is migrated by
writing and verifying the secret copy before the plaintext state is replaced.

## Internal structure

`adapter.py` now contains lifecycle, dependency composition, polling orchestration,
execute dispatch, capability checks, and auth delegation. QR state lives in
`auth.py`; credential classification and persistence in `session.py`; inbound and
outbound profile conversion in `inbound.py` and `outbound.py`; and CDN/media
conversion in `media.py`. The split is behavior-preserving and adds no new Weixin
feature.

## Interactive authentication

The adapter uses the generic API shared by future interactive transports:

- `GET /v1/adapters/{id}/auth`
- `POST /v1/adapters/{id}/auth/start`
- `POST /v1/adapters/{id}/auth/cancel`

States are `logged_out`, `waiting_user`, `authenticated`, `expired`, and `failed`.
The QR challenge is returned as `challenge.qr_uri`. Startup without a session is
valid and reports adapter health as `DEGRADED`; confirmed login changes it to
`RUNNING`. Error code `-14` deletes persisted credentials and returns to
`logged_out`, allowing a fresh generic auth flow.

## Feature matrix

| Feature | Receive | Send |
| --- | ---: | ---: |
| Private message | Yes | Yes, after a context token is observed |
| Text | Yes | Yes |
| Reply | Quoted message ID or stable synthetic reference | No |
| Image | CDN download/decrypt | CDN encrypt/upload |
| Voice/audio | CDN download/decrypt | No |
| Video | CDN download/decrypt | CDN encrypt/upload |
| File | CDN download/decrypt | CDN encrypt/upload |
| Typing | No inbound event | Yes |
| Cursor persistence | Yes | N/A |
| Session persistence | Yes | N/A |
| Reconnect | Bounded exponential retry | Shared connection |

Endpoint IDs are the Weixin user IDs and remain opaque to Core. Sending requires
the latest `context_token`, so the user must first message the account. Unsupported
items are preserved as a raw Weixin segment.

## Media security

Gateway media always crosses the adapter as an opaque `media_id`. Weixin CDN
payloads use AES-ECB with protocol-compatible PKCS#7 padding. Random keys and file
keys are created per upload. Local filesystem paths are never exposed to the
adapter, and encrypted query parameters are not emitted as event metadata.

## Test status

`INTEGRATION_PASS`: deterministic tests cover QR start/cancel/expiry/confirmation,
receive, text/media send, typing, encrypted-media boundary calls, token invalidation,
state/secret split, legacy plaintext migration, credential deletion, and restart
recovery using the same state and secret stores.

`REAL_SMOKE_PENDING`: run `python scripts/smoke/weixin.py --image <path>` against
an authorized account. The script prints `REAL_SMOKE_PASS` only after login,
text/media receive, text/media/typing send, Gateway restart recovery, token
invalidation, and re-login all succeed.

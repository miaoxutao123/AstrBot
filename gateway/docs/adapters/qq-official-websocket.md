# QQ Official WebSocket Adapter

> QQ Official WebSocket is Tencent's official QQ Bot gateway transport. It is
> independent from the OneBot v11 adapter.

The adapter uses Tencent App credentials to obtain a dynamic access token,
discovers the official Gateway, and handles HELLO, IDENTIFY, heartbeat ACK,
READY, RESUME, reconnect, and invalid-session signaling. Install with
`astrbot-gateway[qq_official]`.

Static App ID/secret references use `AdapterContext.get_secret()`. The dynamic
access token and expiry use `AdapterSecretStore`. `session_id`, sequence and resume
URL are ordinary `AdapterStateStore` metadata. Neither token is written to SQLite
state.

If Tencent rejects a still-locally-valid cached token with HTTP 401/403, the
adapter deletes it from SecretStore, refreshes it once from AppID/AppSecret, and
retries the request once. It does not enter an unbounded authentication loop.

| Feature | Receive | Send | Automated test |
| --- | ---: | ---: | --- |
| C2C | Yes | Text, reply, image | Integration |
| Group | Yes | Text, reply, image | Integration |
| Guild/channel | Yes | Text, reply | Integration |
| Direct message | Yes | Text, reply | Integration |
| Mention | Preserved in text/raw elements | No standard send | Integration |
| Unknown event/element | Raw platform event/segment | No | Integration |
| File/audio/video upload | Attachment receive | Not implemented | Not claimed |
| Reconnect / resume | Yes | N/A | Gateway protocol tests |
| Heartbeat ACK timeout | Supervised reconnect | N/A | Gateway protocol tests |

The package is divided into `common/` protocol models, inbound/outbound/media
conversion and WebSocket-only lifecycle. A future QQ Official webhook adapter can
feed normalized callbacks into the same common converters; the webhook transport
itself remains `NOT_STARTED`.

Rate limits map to `RATE_LIMITED` with `retry_after`; authentication, timeout,
delivery, invalid command and transport failures retain distinct safe Gateway
errors. `REAL_SMOKE_PENDING`; use
`python scripts/smoke/qq_official_websocket.py` with an authorized bot and only
claim domains enabled for that account.

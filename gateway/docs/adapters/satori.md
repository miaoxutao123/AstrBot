# Satori Adapter

Satori is a multi-platform message protocol transported over WebSocket events and
HTTP operations. It is not treated as a downstream platform SDK: endpoint
identity remains `im / satori / <instance> / <adapter-owned-route>` while
`satori_platform` and `satori_self_id` remain diagnostic metadata.

Install with `astrbot-gateway[satori]`. Configure WebSocket/API URLs and an
optional static token environment reference. One server may expose multiple
logins; the endpoint encodes the selected platform, bot account and channel so
outbound REST headers route through the same login without Core parsing it.

| Feature | Receive | Send | Automated test |
| --- | ---: | ---: | --- |
| Private/direct | Yes | Yes | Integration |
| Guild/channel | Yes | Yes | Integration |
| Text / mention / reply | Yes | Yes | Integration |
| Image | Yes | Yes | Integration |
| Audio / video / file | Yes | Yes | Conversion |
| Unknown XML | Raw | No | Integration |
| Multiple downstream logins | Yes | Yes | Integration |
| Heartbeat / reconnect | Yes | N/A | Lifecycle simulation |

Sequence is ordinary namespaced state. The configured token is a static host
secret. Media enters Gateway through opaque `media_id` references; outbound media
is encoded at the adapter boundary. `REAL_SMOKE_PENDING`; use
`python scripts/smoke/satori.py` against an authorized server.

WebSocket HTTP handshake responses 401/403 are treated as terminal
authentication failure. Provider-specific authentication rejection after an
established signaling connection remains part of real-environment smoke.

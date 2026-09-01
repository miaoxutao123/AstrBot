# Adapter API v1 Final Review

Decision: **Adapter API v1 is FROZEN**.

## Transport diversity

| Adapter | Transport style | Auth | State | Media | Special pressure |
| --- | --- | --- | --- | --- | --- |
| OneBot | Forward/reverse WebSocket | Static token | reconnect identifiers | IM media | protocol adapter and two connection directions |
| Telegram | Bot API polling | Static bot token | update offset | rich media | thread, reaction, edit, delete |
| Weixin OC | Long poll | Interactive QR/dynamic token | cursor/account metadata; credentials separate | encrypted CDN | interactive auth and credential migration |
| Satori | WebSocket + HTTP | Optional static token/login protocol | sequence and multiple accounts | protocol-dependent | multi-platform protocol and account routing |
| QQ Official | Official Gateway WS + REST | App credentials + dynamic token | session/resume/sequence | official download/upload | heartbeat ACK, resume and same platform via different protocol |

All five use the same `TransportAdapter`, `AdapterContext`, identity, event,
command, capability, state, secret, media and optional-auth contracts. Neither
Satori nor QQ Official added a platform field to Core. OneBot QQ and Tencent QQ
Official coexist because Core routes `adapter_type` and `adapter_id`, not a notion
of QQ.

## Freeze checklist

- Core imports no IM profile, adapter, QQ, Satori, Telegram, Weixin, SDK, or
  FastAPI module.
- No adapter receives Runtime, raw SQLite, the unscoped secret backend, or a media
  filesystem path.
- Runtime failure isolation and entry-point discovery remain unchanged.
- Fake IM, Sensor and Robot remain contract-equivalent and pass regression tests.
- Satori multiple login/account routing stays in endpoint IDs and metadata.
- QQ Official WebSocket shares models, inbound, outbound and media with the future
  webhook boundary and imports no OneBot protocol code.
- Base install remains PyYAML plus pycryptodome; all five transport/API SDK sets
  are optional extras.

## Frozen public surface

Version 1 freezes `TransportAdapter`, `AdapterContext`, `AdapterDescriptor`,
`EndpointRef`, `GatewayEvent`, `GatewayCommand`, `CommandResult`, `Capability`,
`AdapterState`, `AdapterStateStore`, `AdapterSecretStore`, `MediaStore`, generic
interactive auth, and the `astrbot_gateway.adapters` entry-point group.

Compatible v1 evolution may add an optional method with a safe default, capability
vocabulary, payload schema, adapter, or metadata. It must not remove/rename public
methods or endpoint fields, change existing semantics, add required Context
services, or change descriptor identity semantics. Such a breaking change requires
`GATEWAY_API_VERSION = 2`.

Real smoke remains an independent maturity signal. Automated protocol integration
is sufficient for the architecture freeze, but no adapter is labeled
`REAL_SMOKE_PASS` without an authorized external run.

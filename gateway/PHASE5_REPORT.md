# Phase 5 Report

Historical note: this report records the P5 implementation baseline. P5.1 later
moved Weixin login/context credentials from ordinary state to the separate
encrypted-capable `AdapterSecretStore`; see `P5.1_REPORT.md`.

## Implemented

- Added generic interactive Adapter authentication state and the three required
  `/v1/adapters/{id}/auth` endpoints; no Weixin-specific Core API was added.
- Added Weixin OC QR start/poll/cancel/expiry/confirmation and session recovery.
- Persisted token, account, server base URL, long-poll cursor, and context tokens
  exclusively through the injected namespaced `AdapterStateStore`.
- Added long polling with health reporting and bounded retry; protocol error `-14`
  clears the persisted session and permits re-login.
- Added private text and inbound reply recognition, typing, inbound media
  download/decryption, and outbound image/video/file encryption and CDN upload
  through the opaque media boundary.
- Added a dedicated optional dependency group, CI job, documentation, tests, and a
  protected real-environment smoke script.

## Architecture and contract

Interactive auth is an optional defaulted `TransportAdapter` contract returning
`not_required` for ordinary adapters. Runtime delegates without knowing any QR,
OAuth, device-pairing, or Weixin details. `AuthChallenge` can carry a QR URI,
Gateway media ID, verification code, and instructions. Core still imports no IM
profile or transport SDK.

## Verification

Local verification at implementation time: 85 tests passed; Ruff formatting and
lint, strict mypy, and pyright passed. CI receives a separate Weixin matrix on
Python 3.10 and 3.13 in addition to existing quality, Core, API, contract, OneBot,
and Telegram jobs.

## Real smoke status

`REAL_SMOKE_PENDING`. No authorized personal Weixin environment was available.
The smoke script cannot print `REAL_SMOKE_PASS` until the full specification
sequence—including restart recovery, invalid-token detection, and re-login—has
been completed against the real service.

## Known limitations

- Weixin sends require a context token learned from an inbound user message.
- QR is exposed as a URI; the optional generic challenge `media_id` is not populated.
- Voice is accepted inbound but not sent in Phase 5; transcoding belongs outside
  this transport adapter.
- The service's exact reply rendering and account-side logout behavior still need
  real-environment confirmation.
- Outbound reply is not advertised because the audited upstream source implements
  inbound quote reconstruction but no reliable reply-send operation.

## Scope stop

No Satori, Phase 6 Adapter API freeze, MCP, or later-phase work was started.

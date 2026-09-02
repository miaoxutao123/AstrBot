# P7C Control Plane Report

## Baseline

Implemented on `customization` with Adapter API v1 unchanged.

## Managed connections

`ManagedAdapterStore` persists WebUI-owned instances in SQLite; YAML instances remain read-only.
Host startup combines both, with YAML IDs taking precedence. Secrets are stored in the configured
backend under `managed-adapter/<id>/<field>`. SQLite holds only opaque references and API reads
return `{ "configured": true }`.

Managed CRUD, type metadata, instance inspection, and runtime registration are synchronized.
Managed values are preloaded into the Host resolver before adapters start.

## UI and generic authentication

Gateway serves a standalone same-origin control plane at `/ui`: Overview, Connections, Agents,
Endpoints, and System. It does not call legacy AstrBot `/api` routes. Connections supports managed
create/delete and generic authentication QR URI, verification code, instructions, start, and cancel.

## External Agents

The registry uses hashed one-time enrollment tokens and hashed Agent keys. Normal Bearer auth
supports heartbeats, metadata-only self updates, list/detail, and immediate revocation. Manifest
and bootstrap document registration and self APIs. The UI creates a separate environment command
and a bootstrap prompt that deliberately excludes the token.

## Verification

```text
ruff check .                         PASS
mypy                                 PASS
pytest -q -p no:cacheprovider tests  126 passed
```

Coverage includes secret redaction, persistence, UI serving, catalog, enrollment/register/heartbeat/
revoke, self metadata updates, manifest discovery, and existing adapter/API/SDK/Bridge tests.

## Known limitations

No real QQ Official or Weixin account was available for provider smoke tests. The UI is deliberately
a lightweight Gateway control plane, not the legacy AstrBot dashboard. Central Agent routing remains
out of scope by design.

## Next phase

Run QQ Official and Weixin OC smoke tests, then address provider-specific UX findings without
expanding into central Agent routing.

# P7B Report

Baseline: `ab0cf8a55bd2f12636ffa608d4183b26a47d873f`.

## Delivered

- Authenticated `/v1/discovery` aggregates adapter state, observed endpoints, capability traits, derived direction and caller authorization. Direction is derived from profile traits; Adapter API v1 remains unchanged.
- Public `/.well-known/astrbot-gateway` contains only stable protocol links, while authenticated `/v1/agent/bootstrap` supplies inventory and generic installation metadata without secrets.
- Python SDK adds `GatewayInventory`, `AdapterInfo`, `EndpointInfo`, `CapabilityInfo`, `discover()` and `find_endpoints()`.
- `astrbot-gateway-agent` is an independent generic Bridge supporting command argv and HTTP invocation, versioned JSON stdin/stdout protocol, SQLite session mapping, per-session serialization, bounded concurrency/timeouts/output and automatic current-conversation replies.
- `astrbot-gateway-mcp` exposes discovery, endpoint, IM and generic execute tools strictly through the public SDK.
- Bootstrap, self-configuration and generic wrapper documentation are included.

## Security and limitations

Bridge configuration stores an API-key environment-variable name only. Command execution uses argv (`shell=False`) and an environment allowlist. No Gateway inventory is persisted in session storage, and no agent-specific integrations exist. The first protocol only supports text replies; media and real Harness smoke remain operational/manual validation work.

## CI and manual smoke

Run Gateway tests plus SDK/Bridge/MCP package tests. For a real Harness, give it only Gateway URL, `GATEWAY_API_KEY`, and the bootstrap instructions; it must create its own wrapper and configuration, run doctor, then complete FakeIM → Gateway → Bridge → Harness → Gateway → FakeIM without repository changes.

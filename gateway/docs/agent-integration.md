# Agent Integration Contract

Gateway transports events and commands; an external Agent owns reasoning,
memory, tools, its native session, and a Gateway adapter or sidecar. Start from
`/.well-known/astrbot-gateway`, follow returned registration and bootstrap
links, then read `agent_integration`. Do not guess API paths or modify Gateway.

Use **HTTP mode** for a persistent Agent runtime and **command mode** for a CLI
Agent. Convert `astrbot.agent.invoke.v1` into the native AgentFlow and return
`astrbot.agent.result.v1`. Preserve canonical structured segments. Map the
Gateway session key to the native session and return `external_session_id` so
the next invocation continues the same conversation.

Use the bootstrap-provided commands link for proactive output. Keep the single
registered `GATEWAY_API_KEY` as the authoritative credential for bootstrap,
events, commands, and heartbeat. Validate the boundary with:

```bash
astrbot-gateway-agent doctor --config agent-gateway.yaml
```

The examples in `packages/agent-bridge/examples/` are generic protocol
templates, not production Agent integrations.

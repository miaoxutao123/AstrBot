# AstrBot Gateway Agent Bootstrap

1. Read `/.well-known/astrbot-gateway`.
2. Read the API key from `GATEWAY_API_KEY`; never write its value to configuration.
3. Call `/v1/agent/bootstrap`, then `/v1/discovery`.
4. Install `astrbot-gateway-agent` and, for proactive actions, `astrbot-gateway-mcp`.
5. Create a local command or HTTP wrapper that implements `astrbot.agent.invoke.v1` and returns `astrbot.agent.result.v1`.
6. Run `astrbot-gateway-agent doctor --config agent-gateway.yaml`.
7. Start `astrbot-gateway-agent run --config agent-gateway.yaml`, then verify an inbound event and reply.

The Bridge owns only event delivery, session routing and current-conversation replies. Use MCP or the SDK for proactive cross-endpoint actions.

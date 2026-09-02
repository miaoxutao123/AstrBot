# Self-configuring Agent

Give an Agent the Gateway URL, the environment variable name `GATEWAY_API_KEY`, and the bootstrap instructions in [agent-bootstrap.md](agent-bootstrap.md). It discovers the Gateway through the well-known manifest, chooses command or HTTP invoke mode for itself, creates its own wrapper, runs doctor, then starts the generic Bridge. No platform-specific or Harness-specific code is required in AstrBot-Gateway.

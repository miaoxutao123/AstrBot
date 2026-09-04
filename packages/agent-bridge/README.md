# AstrBot Gateway Agent Bridge

Generic command and HTTP invocation bridge for any Agent Harness that speaks
`astrbot.agent.invoke.v1`.

The Bridge is protocol transport, not an Agent Runtime. Generic command and
HTTP adapter templates are in `examples/`; they demonstrate the stable
`invoke.v1` / `result.v1` boundary and session-id round trip without depending
on a particular Agent framework.

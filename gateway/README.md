# Agent Transport Gateway

Agent Transport Gateway is an independent, lightweight I/O and transport core
extracted from lessons learned in AstrBot's platform layer. It converts transport
input into neutral events and routes neutral commands back to adapters. It does not
contain an agent runner, model provider, prompt system, memory, or transport SDK.

Phase 1 provides only the dependency-free Python core and fake adapters used to
validate the abstraction. HTTP, WebSocket, storage, and real platform adapters are
intentionally deferred.

```bash
cd gateway
python -m pytest
ruff check .
mypy
```

See `docs/architecture.md` and `docs/protocol.md` for the current contracts.

# Agent Transport Gateway

Agent Transport Gateway is an independent, lightweight I/O and transport gateway
extracted from lessons learned in AstrBot's platform layer. It converts transport
input into neutral events and routes neutral commands back to adapters. It does not
contain an agent runner, model provider, prompt system, memory, or transport SDK.

The base installation contains the dependency-free Python Core. Phase 2 adds an
optional FastAPI HTTP/WebSocket boundary; storage and real platform adapters remain
deferred.

```bash
cd gateway
python -m pip install -e ".[api]"
python -m pytest
ruff check .
mypy
```

The API is an application factory so a host can configure adapter instances and
secrets without exposing them to Core:

```python
from gateway.api import ApiKey, create_app
from gateway.core import AdapterRegistry, AdapterRuntime, MemoryEventBus

event_bus = MemoryEventBus()
runtime = AdapterRuntime(AdapterRegistry(), event_bus)
app = create_app(
    runtime,
    event_bus,
    [ApiKey("local", "replace-me", frozenset({"*"}))],
)
```

Run that module with an ASGI server such as `uvicorn host:app`. The application
lifespan starts the event bus and adapters before accepting work and stops them in
the reverse order.

See `docs/architecture.md` and `docs/protocol.md` for the current contracts.

# AstrBot-Gateway

> AstrBot-Gateway is an independent derivative of AstrBot focused on transport
> and messaging gateway functionality. It is not an official AstrBot distribution.

AstrBot-Gateway is an independent, lightweight I/O and transport gateway
extracted from lessons learned in AstrBot's platform layer. It converts transport
input into neutral events and routes neutral commands back to adapters. It does not
contain an agent runner, model provider, prompt system, memory, or transport SDK.

Phase 6 validates the contract across OneBot, Telegram, Weixin, Satori and Tencent
QQ Official WebSocket. Adapter API v1 is now **FROZEN** with the compatibility
policy in `docs/adapter-api-v1-final-review.md`.

The base installation contains the transport-neutral Python Core, YAML host
configuration, CLI, media boundary, and adapter state persistence. FastAPI and
OneBot SDK dependencies remain optional extras.

```bash
cd gateway
python -m pip install -e ".[all]"
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

For persistent adapter login credentials, configure `secrets.type` as
`encrypted_file` and provide a base64-encoded 32-byte key through
`ASTRBOT_GATEWAY_MASTER_KEY`. The key must not be placed in YAML. The default
`memory` secret backend does not persist credentials across restarts.

For a standalone process, copy `gateway.example.yaml`, set the referenced secret
environment variables, and run:

```bash
astrbot-gateway check -c gateway.yaml
astrbot-gateway adapters -c gateway.yaml
astrbot-gateway run -c gateway.yaml
```

Installation groups are intentionally separated:

```bash
pip install astrbot-gateway
pip install "astrbot-gateway[api]"
pip install "astrbot-gateway[onebot]"
pip install "astrbot-gateway[telegram]"
pip install "astrbot-gateway[weixin]"
pip install "astrbot-gateway[satori]"
pip install "astrbot-gateway[qq_official]"
```

OneBot supports forward WebSocket client mode and an aiocqhttp-compatible reverse
WebSocket server mode. See `docs/adapters/onebot.md` for configuration and the
tested feature matrix.

Telegram supports Bot API polling, private/group/channel/thread conversations,
albums, standard media, edit, delete, reaction, and typing operations. See
`docs/adapters/telegram.md` for its feature matrix and real-smoke status.

Weixin OC supports generic QR authentication, separated credential/cursor persistence,
private messages, encrypted CDN media, inbound reply recognition, typing, and
bounded reconnect. See
`docs/adapters/weixin.md` for setup and the protected real-smoke sequence.

Satori supports multi-platform/multi-login WebSocket events and HTTP message
operations. Tencent QQ Official WebSocket supports the official Gateway lifecycle,
C2C/group/guild/direct messages and REST media; it is independent from OneBot.

See `docs/architecture.md`, `docs/protocol.md`, and
`docs/adapter-api-v1-review.md` for the current contracts and pre-freeze findings.

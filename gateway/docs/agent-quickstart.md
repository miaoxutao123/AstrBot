# Python Agent Quickstart

Start Gateway with an API key that has `events:read`, `commands:send`, and any
adapter read scopes you intend to call:

```bash
astrbot-gateway run --config gateway.yaml
```

Install the independent agent SDK from this repository while developing:

```bash
pip install ./packages/python-sdk
```

Set the URL and key, then run the echo agent:

```bash
export GATEWAY_URL=http://127.0.0.1:6186
export GATEWAY_API_KEY=your-agent-key
python examples/python_echo_agent.py
```

The client reconnects its event subscription and asks Gateway for best-effort
replay after the most recently received event. `reply()` derives the target,
message ID, command ID, payload schema, and correlation ID from the event.

```python
async with AsyncGatewayClient(url, api_key=key) as gateway:
    async for event in gateway.events(event_type="im.message"):
        if event.message:
            await gateway.reply(event, f"echo: {event.message.text}")
```

`im.message` is the current stable Gateway wire event type. The SDK's
`event.message` convenience view is present whenever the payload schema is
`im.message.v1`.

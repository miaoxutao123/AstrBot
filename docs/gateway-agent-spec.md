# AstraBot Unified Gateway — Agent Integration Spec

> For external Agent systems (Hermes, Dify, Coze, custom Agents, etc.)

## 1. Overview

AstraBot Unified Gateway exposes **three inbound channels** and **one outbound channel** for your Agent:

| Channel | Direction | Protocol | Best For |
|---------|-----------|----------|----------|
| **Webhook** | AstraBot → Agent | HTTP POST (push) | Cloud agents, serverless |
| **Long Polling** | Agent → AstraBot | HTTP GET (pull) | Firewalled / local agents |
| **WebSocket** | Bidirectional | WS JSON | High-frequency / streaming |
| **HTTP Reply** | Agent → AstraBot | HTTP POST | Universal reply path |

You can implement **one or all** channels. Pick what fits your architecture.

## 2. Authentication

All gateway endpoints require an **API Key**.

- Header: `Authorization: Bearer abk_xxx` or `X-API-Key: abk_xxx`
- Query: `?api_key=abk_xxx`

Create the key in AstraBot Dashboard → Extensions → API Key. Scopes needed: `im` + `gateway`.

## 3. Webhook Channel

AstraBot pushes events to your webhook URL as soon as a message arrives.

### 3.1 Endpoint Contract

```http
POST <your-webhook-url>
Content-Type: application/json
Authorization: Bearer <secret>

# Body — MessageEnvelope
{
  "event_id": "evt_...",
  "type": "im.message.receive",
  "version": "1.0",
  "timestamp": 1718340000,
  "platform": {"id": "...", "name": "telegram", "type": "telegram"},
  "session": {"umo": "...", "session_id": "...", "message_type": "FriendMessage", "group_id": ""},
  "sender": {"id": "...", "name": "...", "role": "member"},
  "message": {"text": "...", "chain": [...]},
  "metadata": {"is_at": true, "is_wake": true, "is_private": true}
}
```

### 3.2 Expected Response

AstraBot **does not wait** for your response. Reply via the HTTP Reply channel (see §6).

Return HTTP 200/202 quickly. If you need >30s, return 202 and reply later.

### 3.3 Hermes Example

```python
# Hermes webhook handler (FastAPI example)
from fastapi import FastAPI, Request, Header

app = FastAPI()

@app.post("/astrbot/events")
async def on_astrbot_event(request: Request, authorization: str = Header(None)):
    envelope = await request.json()
    event_id = envelope["event_id"]
    umo = envelope["session"]["umo"]
    text = envelope["message"]["text"]
    
    # Run Hermes logic asynchronously
    asyncio.create_task(hermes_process(event_id, umo, text))
    return {"received": True}

async def hermes_process(event_id, umo, text):
    reply = await hermes.chat(text)
    await send_back_to_astrbot(umo, reply)
```

## 4. Long Polling Channel

Use this when your Agent cannot expose a public HTTP endpoint.

### 4.1 Polling API

```http
GET /api/gateway/events?timeout=30&platform=telegram
Authorization: Bearer abk_xxx
```

**Response:**
```json
{
  "events": [
    {
      "event_id": "evt_...",
      "type": "im.message.receive",
      "payload": { /* MessageEnvelope */ }
    }
  ]
}
```

### 4.2 ACK (Required)

After processing, acknowledge to prevent duplicate delivery:

```http
POST /api/gateway/events/ack
Authorization: Bearer abk_xxx
Content-Type: application/json

{"event_ids": ["evt_..."]}
```

### 4.3 Hermes Polling Loop

```python
import asyncio, aiohttp

async def astrbot_poll_loop(api_key: str):
    async with aiohttp.ClientSession(
        headers={"Authorization": f"Bearer {api_key}"}
    ) as session:
        while True:
            async with session.get(
                "http://astrbot:6185/api/gateway/events?timeout=30"
            ) as resp:
                data = await resp.json()
                for event in data.get("events", []):
                    umo = event["payload"]["session"]["umo"]
                    text = event["payload"]["message"]["text"]
                    reply = await hermes.chat(text)
                    await send_back_to_astrbot(umo, reply)
                    # ACK
                    await session.post(
                        "http://astrbot:6185/api/gateway/events/ack",
                        json={"event_ids": [event["event_id"]]}
                    )
```

## 5. WebSocket Channel

Best for low-latency, bidirectional chat.

### 5.1 Connection

```
WS /api/gateway/stream?api_key=abk_xxx
```

### 5.2 Protocol

**AstraBot → Agent (event push):**
```json
{"op": "event", "data": { /* MessageEnvelope */ }}
```

**Agent → AstraBot (ping):**
```json
{"op": "ping"}
```
**Response:**
```json
{"op": "pong"}
```

**Agent → AstraBot (send message):**
```json
{
  "op": "send_message",
  "ref_event_id": "evt_...",
  "data": {
    "umo": "telegram:FriendMessage:...",
    "message": [{"type": "plain", "text": "Hello"}]
  }
}
```

**Response:**
```json
{"op": "send_message_result", "data": {"success": true}}
```

### 5.3 Hermes WS Example

```python
import asyncio, websockets, json

async def astrbot_ws_loop(api_key: str):
    uri = f"ws://astrbot:6185/api/gateway/stream?api_key={api_key}"
    async with websockets.connect(uri) as ws:
        while True:
            msg = json.loads(await ws.recv())
            if msg["op"] == "event":
                payload = msg["data"]
                umo = payload["session"]["umo"]
                text = payload["message"]["text"]
                reply = await hermes.chat(text)
                await ws.send(json.dumps({
                    "op": "send_message",
                    "data": {
                        "umo": umo,
                        "message": [{"type": "plain", "text": reply}]
                    }
                }))
            elif msg["op"] == "pong":
                pass
```

## 6. Reply Channel (HTTP API)

Regardless of which inbound channel you use, reply is always via HTTP:

```http
POST /api/v1/im/message
Authorization: Bearer abk_xxx
Content-Type: application/json

{
  "umo": "telegram:FriendMessage:telegram!123456789",
  "message": [
    {"type": "plain", "text": "Reply from Hermes"},
    {"type": "image", "url": "https://example.com/img.png"}
  ]
}
```

### 6.1 UMO Format

`platform_name:MessageType:session_id`

Examples:
- `telegram:FriendMessage:telegram!123456789` (private)
- `wecom:GroupMessage:wecom!group_123` (group)

### 6.2 Message Chain Types

| Type | Fields | Example |
|------|--------|---------|
| `plain` | `text` | `{"type":"plain","text":"hi"}` |
| `image` | `url` or `file` | `{"type":"image","url":"https://..."}` |
| `at` | `qq` or `name` | `{"type":"at","qq":"123"}` |
| `file` | `url` or `file` | `{"type":"file","url":"https://..."}` |
| `record` | `url` or `file` | `{"type":"record","url":"https://..."}` |

## 7. MessageEnvelope Schema

```json
{
  "event_id": "string",
  "type": "im.message.receive",
  "version": "1.0",
  "timestamp": 1718340000,
  "platform": {"id": "string", "name": "string", "type": "string"},
  "session": {"umo": "string", "session_id": "string", "message_type": "string", "group_id": "string"},
  "sender": {"id": "string", "name": "string", "role": "member|admin"},
  "message": {"text": "string", "chain": [{"type": "string", "data": {}}]},
  "metadata": {"is_at": true, "is_wake": true, "is_private": true, "raw_message_id": "string"}
}
```

## 8. Error Handling

| Error | What To Do |
|-------|-----------|
| `401 Unauthorized` | Check API key validity and scope (`gateway` + `im`) |
| `403 Forbidden` | Key exists but lacks required scope |
| `429 Too Many Requests` | Back off and retry with exponential backoff |
| Webhook timeout | Return 202 immediately; reply async via HTTP API |
| WS disconnect | Reconnect with exponential backoff. Unacked events stay in queue for 60s. |

## 9. Minimal Hermes Integration Checklist

- [ ] Create `gateway` scoped API Key in AstraBot Dashboard
- [ ] Implement **one** inbound channel (Webhook recommended for cloud, LongPoll for local)
- [ ] Implement reply via `POST /api/v1/im/message`
- [ ] Parse `MessageEnvelope` and extract `session.umo` + `message.text`
- [ ] Return ACK for LongPoll; return 200 for Webhook
- [ ] Handle reconnect / retry for WebSocket

---

> Spec version: 1.0 | Branch: `feat/unified-gateway`

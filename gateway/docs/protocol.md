# Gateway Protocol v1 Draft

This document defines the transport-neutral v1 data contract and its Phase 2 HTTP
and WebSocket encoding.

## Endpoint

```json
{
  "transport": "telegram",
  "adapter_id": "telegram-main",
  "endpoint_id": "user:123456"
}
```

Endpoint IDs are opaque to Core. Valid non-IM examples include MQTT topic names,
ROS2 controller paths, serial device addresses, and sensor identifiers.

## Payload envelope

```json
{
  "schema": "sensor.temperature.v1",
  "data": {
    "value": 24.5,
    "unit": "celsius"
  }
}
```

Unknown schemas must pass through Core unchanged. A future network API will require
`data` to be JSON-serializable, but the in-process Phase 1 model does not interpret
or normalize it.

## Event

```json
{
  "id": "evt_01",
  "source": {
    "transport": "sensor",
    "adapter_id": "home",
    "endpoint_id": "temperature/livingroom"
  },
  "type": "telemetry.temperature",
  "payload": {
    "schema": "sensor.temperature.v1",
    "data": {"value": 24.5, "unit": "celsius"}
  },
  "timestamp": 1788138000.0,
  "metadata": {},
  "correlation_id": null
}
```

Event IDs are stable inputs for future deduplication, delivery retry, trace lookup,
and correlation. Adapters should preserve a stable platform event ID when one is
available or generate one at the adapter boundary.

## Command

```json
{
  "id": "cmd_01",
  "target": {
    "transport": "robot",
    "adapter_id": "robot-01",
    "endpoint_id": "/base_controller"
  },
  "type": "robot.move",
  "payload": {
    "schema": "robot.motion.v1",
    "data": {"linear_x": 0.3, "angular_z": 0.1}
  },
  "metadata": {},
  "correlation_id": "request_01"
}
```

Core does not interpret the motion fields. It verifies that the addressed adapter
is online and that the endpoint declares `robot.move`, then delegates execution.

## Command result

Success:

```json
{
  "command_id": "cmd_01",
  "status": "success",
  "external_id": "platform-message-9988",
  "error": null
}
```

Failure:

```json
{
  "command_id": "cmd_01",
  "status": "failed",
  "external_id": null,
  "error": {
    "code": "CAPABILITY_NOT_SUPPORTED",
    "message": "capability is not supported: robot.fly",
    "retryable": false,
    "details": {}
  }
}
```

Allowed statuses are `accepted`, `success`, and `failed`. A failed result always has
an error; a non-failed result never has one.

Stable error codes are:

```text
ADAPTER_NOT_FOUND
ADAPTER_OFFLINE
ENDPOINT_NOT_FOUND
EVENT_NOT_FOUND
CAPABILITY_NOT_SUPPORTED
INVALID_COMMAND
AUTH_FAILED
RATE_LIMITED
TRANSPORT_ERROR
DELIVERY_FAILED
TIMEOUT
INTERNAL_ERROR
```

Future APIs must not expose Python tracebacks. Messages and details must not contain
tokens, passwords, or complete secrets.

## Capability

```json
{
  "name": "im.send_image",
  "version": "1",
  "schema": null
}
```

Capabilities may be static at adapter scope or dynamic at endpoint scope. Capability
does not grant authorization; Phase 2 caller scopes will be evaluated separately.

## IM message profile

`im.message.v1` is an optional profile layered on the generic payload envelope:

```json
{
  "schema": "im.message.v1",
  "data": {
    "message_id": "123",
    "conversation": {"type": "private", "id": "456"},
    "sender": {"id": "123456", "display_name": "Alice"},
    "segments": [{"type": "text", "text": "hello"}],
    "reply_to": null
  }
}
```

Segment type vocabulary for v1:

```text
text image audio video file mention mention_all reply location forward card json raw
```

An adapter should use `raw` only when a platform value cannot be represented by a
standard segment. Unknown platform data must not be silently dropped.

Outbound IM commands use `im.message.outbound.v1`. Their data includes `segments`
and may include `reply_to`; the destination remains the command's opaque
`endpoint_id`. Media segments never expose a host filesystem path. They reference
an opaque `media_id` from the media service together with safe metadata such as
MIME type, filename, and size.

Rich IM operations use small versioned payloads: `im.message.edit.v1` contains a
message ID and replacement segments; `im.message.delete.v1` contains a message ID;
`im.reaction.v1` contains a message ID, optional emoji, and optional `big` flag;
and `im.typing.v1` contains an activity name. Adapters advertise only the
operations they implement.

## Correlation and logging

Commands created in response to an event should normally copy the event ID into
`correlation_id`, or use a higher-level request correlation ID shared by both.
Structured logs must carry the available event ID or command ID together with
correlation ID, adapter ID, and endpoint ID.

## HTTP API

`GET /v1/health` is intentionally unauthenticated and contains no configuration or
secrets. All other REST routes require either `Authorization: Bearer <key>` or
`X-API-Key: <key>`.

| Route | Required scope |
| --- | --- |
| `GET /v1/adapters`, `GET /v1/adapters/{id}` | `adapters:read` |
| `POST /v1/adapters/{id}/start`, `/stop`, `/restart` | `adapters:manage` |
| `GET /v1/endpoints`, `GET /v1/endpoints/{id}/capabilities` | `adapters:read` |
| `POST /v1/commands` | `commands:send` |
| `GET /v1/events/{id}` | `events:read` |
| `POST /v1/media` | `media:write` |
| `GET /v1/media/{id}` | `media:read` |
| `DELETE /v1/media/{id}` | `media:write` |

Commands targeting robot or hardware transports additionally require
`hardware:control`. A wildcard `*` grants all current scopes. Endpoint resource IDs
are opaque strings returned by the endpoints API and must not be parsed by clients.

HTTP errors use one stable envelope:

```json
{
  "error": {
    "code": "INVALID_COMMAND",
    "message": "request validation failed",
    "retryable": false,
    "details": {}
  }
}
```

Media failures use stable `MEDIA_NOT_FOUND` or `MEDIA_INVALID` error codes. Uploads
are bounded by the configured maximum size, filenames are treated as display
metadata rather than paths, and expired objects may be removed by store cleanup.

## WebSocket event API

Connect to `GET /v1/events/ws` with an API key having `events:read`. Optional query
filters are `transport`, `adapter_id`, and `event_type`; omitted fields and `*`
match all events. Event messages use:

```json
{"type": "event", "data": {"id": "evt_01", "source": {}, "type": "im.message", "payload": {}}}
```

When idle, the server sends a heartbeat containing a timestamp and the most recent
cursor. A reconnecting client may pass `last_event_id` (or the compatibility alias
`cursor`) to replay matching events still present in process memory. This is a
best-effort bounded replay, not durable delivery. The server emits a `gap` envelope
when the cursor is absent or replay is truncated. A client whose bounded delivery
queue overflows receives a retryable `DELIVERY_FAILED` error and close code 1013.

Authentication failures close the WebSocket with 4401; insufficient scope uses
4403. Every connection subscription is removed on disconnect or server-side close.

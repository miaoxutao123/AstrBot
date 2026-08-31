# Gateway Protocol v1 Draft

This document defines the Phase 1 data contract. It is transport-neutral and will
be used by the Phase 2 HTTP and WebSocket encodings. All examples are JSON-shaped;
Phase 1 itself does not implement network serialization.

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
text image audio video file mention mention_all reply location forward json raw
```

An adapter should use `raw` only when a platform value cannot be represented by a
standard segment. Unknown platform data must not be silently dropped.

## Correlation and logging

Commands created in response to an event should normally copy the event ID into
`correlation_id`, or use a higher-level request correlation ID shared by both.
Structured logs must carry the available event ID or command ID together with
correlation ID, adapter ID, and endpoint ID.

## Phase 2 reservations

WebSocket envelopes will use the shape `{ "type": "event", "data": {...} }`.
The event subscription protocol will reserve `cursor` and `last_event_id` even
though Phase 2 MVP will not promise durable replay. These fields are not implemented
in Phase 1.

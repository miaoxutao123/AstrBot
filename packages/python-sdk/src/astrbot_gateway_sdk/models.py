"""Wire-protocol models exposed to agent authors."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceEndpoint:
    """One opaque Gateway endpoint identity."""

    family: str
    adapter_type: str
    adapter_id: str
    endpoint_id: str

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> "SourceEndpoint":
        return cls(
            family=str(value["family"]),
            adapter_type=str(value["adapter_type"]),
            adapter_id=str(value["adapter_id"]),
            endpoint_id=str(value["endpoint_id"]),
        )

    def to_wire(self) -> dict[str, str]:
        return {
            "family": self.family,
            "adapter_type": self.adapter_type,
            "adapter_id": self.adapter_id,
            "endpoint_id": self.endpoint_id,
        }


@dataclass(frozen=True, slots=True)
class IMMessage:
    """Convenience view of an ``im.message.v1`` event payload."""

    id: str
    text: str
    sender: Mapping[str, Any]
    segments: tuple[Mapping[str, Any], ...]
    raw: Mapping[str, Any]

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> "IMMessage":
        segments_value = value.get("segments", [])
        segments = tuple(
            segment
            for segment in segments_value
            if isinstance(segments_value, list) and isinstance(segment, Mapping)
        )
        text = "".join(
            str(data.get("text", ""))
            for segment in segments
            for data in (segment.get("data"),)
            if segment.get("type") == "text" and isinstance(data, Mapping)
        )
        sender = value.get("sender")
        return cls(
            id=str(value.get("message_id", "")),
            text=text,
            sender=sender if isinstance(sender, Mapping) else {},
            segments=segments,
            raw=value,
        )


@dataclass(frozen=True, slots=True)
class GatewayEvent:
    """One event received from the Gateway WebSocket wire protocol."""

    id: str
    type: str
    source: SourceEndpoint
    payload: Mapping[str, Any]
    metadata: Mapping[str, Any]
    correlation_id: str | None
    raw: Mapping[str, Any]

    @property
    def message(self) -> IMMessage | None:
        """Return the standard IM message view when this event carries one."""
        data = self.payload.get("data")
        if self.payload.get("schema") != "im.message.v1" or not isinstance(
            data, Mapping
        ):
            return None
        return IMMessage.from_wire(data)

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> "GatewayEvent":
        source = value.get("source")
        payload = value.get("payload")
        metadata = value.get("metadata")
        if not isinstance(source, Mapping) or not isinstance(payload, Mapping):
            raise ValueError("Gateway event wire payload is invalid")
        return cls(
            id=str(value["id"]),
            type=str(value["type"]),
            source=SourceEndpoint.from_wire(source),
            payload=payload,
            metadata=metadata if isinstance(metadata, Mapping) else {},
            correlation_id=(
                str(value["correlation_id"])
                if value.get("correlation_id") is not None
                else None
            ),
            raw=value,
        )

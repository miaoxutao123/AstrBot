"""Inbound event model."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .endpoint import EndpointRef
from .payload import Payload


@dataclass(slots=True, kw_only=True)
class GatewayEvent:
    """Represent an observation emitted by a transport adapter.

    Args:
        source: Endpoint that produced the event.
        type: Adapter-defined event type.
        payload: Extensible event payload.
        id: Stable identifier used for tracing and deduplication.
        timestamp: Unix timestamp at which the event entered the adapter boundary.
        metadata: Transport metadata not represented by the payload profile.
        correlation_id: Optional request or command correlation identifier.

    Raises:
        ValueError: If the event identifier or type is empty.
    """

    source: EndpointRef
    type: str
    payload: Payload
    id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex}")
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        """Validate transport-level event invariants.

        Raises:
            ValueError: If the event identifier or type is empty.
        """
        if not self.id or not self.id.strip():
            raise ValueError("event id must not be empty")
        if not self.type or not self.type.strip():
            raise ValueError("event type must not be empty")
        if self.timestamp < 0:
            raise ValueError("event timestamp must not be negative")

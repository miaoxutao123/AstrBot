"""Fake IM adapter validating the optional IM profile."""

from collections.abc import Mapping
from typing import Any

from gateway.core import (
    GATEWAY_API_VERSION,
    AdapterDescriptor,
    Capability,
    EndpointRef,
    GatewayEvent,
    Payload,
)

from .base import RecordingAdapter


class FakeIMAdapter(RecordingAdapter):
    """Emit IM profile events and record IM commands."""

    DESCRIPTOR = AdapterDescriptor(
        id="fake-im",
        name="Fake IM",
        version="0.1.0",
        api_version=GATEWAY_API_VERSION,
        transport="im",
        capabilities=(
            Capability("im.send_text"),
            Capability("im.send_image"),
            Capability("im.send_file"),
            Capability("im.reply"),
        ),
    )

    def __init__(
        self,
        instance_id: str = "im-main",
        config: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(instance_id, config)

    async def emit_message(
        self,
        endpoint_id: str,
        text: str,
        message_id: str = "message-1",
    ) -> GatewayEvent:
        """Emit one private IM text message.

        Args:
            endpoint_id: Source endpoint identifier.
            text: Message text.
            message_id: Transport message identifier.

        Returns:
            Event emitted through the Gateway context.
        """
        event = GatewayEvent(
            source=EndpointRef("im", self.instance_id, endpoint_id),
            type="im.message",
            payload=Payload(
                schema="im.message.v1",
                data={
                    "message_id": message_id,
                    "conversation": {"type": "private", "id": endpoint_id},
                    "sender": {"id": endpoint_id, "display_name": "Fake User"},
                    "segments": [{"type": "text", "text": text}],
                    "reply_to": None,
                },
            ),
        )
        await self.emit(event)
        return event

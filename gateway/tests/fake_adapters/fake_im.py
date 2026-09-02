"""Fake IM adapter validating the optional IM profile."""

from collections.abc import Mapping
from typing import Any

from gateway.core import (
    GATEWAY_API_VERSION,
    AdapterDescriptor,
    Capability,
    CommandResult,
    EndpointRef,
    GatewayCommand,
    GatewayEvent,
)
from gateway.profiles.im import (
    IM_MESSAGE_RECEIVE,
    IM_MESSAGE_REPLY,
    IM_MESSAGE_SEND,
    IMConversation,
    IMMessage,
    IMOutboundMessage,
    IMSegment,
    IMSender,
)

from .base import RecordingAdapter


class FakeIMAdapter(RecordingAdapter):
    """Emit IM profile events and record IM commands."""

    DESCRIPTOR = AdapterDescriptor(
        adapter_type="fake-im",
        name="Fake IM",
        version="0.1.0",
        api_version=GATEWAY_API_VERSION,
        family="im",
        capabilities=(
            Capability(IM_MESSAGE_SEND),
            Capability(IM_MESSAGE_REPLY),
            Capability(IM_MESSAGE_RECEIVE),
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
            source=EndpointRef("im", "fake-im", self.instance_id, endpoint_id),
            type="im.message",
            payload=IMMessage(
                message_id=message_id,
                conversation=IMConversation("private", endpoint_id),
                sender=IMSender(endpoint_id, "Fake User"),
                segments=(IMSegment.text(text),),
            ).to_payload(),
        )
        await self.emit(event)
        return event

    async def execute(self, command: GatewayCommand) -> CommandResult:
        """Validate canonical outbound IM payloads before recording commands."""
        if command.type not in {IM_MESSAGE_SEND, IM_MESSAGE_REPLY}:
            raise ValueError(f"unsupported Fake IM command: {command.type}")
        IMOutboundMessage.from_payload(command.payload)
        return await super().execute(command)

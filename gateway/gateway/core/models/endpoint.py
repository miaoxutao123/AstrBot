"""Addressing primitives shared by every transport."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EndpointRef:
    """Identify an entity that can emit events or receive commands.

    The identifier is intentionally transport-neutral. An endpoint may be a chat
    participant, a topic, a sensor, an actuator, or another addressable entity.

    Args:
        transport: Transport family, such as ``telegram`` or ``ros2``.
        adapter_id: Configured adapter instance identifier.
        endpoint_id: Adapter-owned endpoint identifier.

    Raises:
        ValueError: If any identifier is empty.
    """

    transport: str
    adapter_id: str
    endpoint_id: str

    def __post_init__(self) -> None:
        """Validate the address without interpreting adapter-owned identifiers.

        Raises:
            ValueError: If any identifier is empty.
        """
        for field_name, value in (
            ("transport", self.transport),
            ("adapter_id", self.adapter_id),
            ("endpoint_id", self.endpoint_id),
        ):
            if not value or not value.strip():
                raise ValueError(f"{field_name} must not be empty")

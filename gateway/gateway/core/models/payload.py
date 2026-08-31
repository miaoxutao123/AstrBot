"""Extensible payload envelope."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Payload:
    """Carry data under a versioned schema name.

    Core deliberately does not enumerate payload variants. Adapters and consumers
    may provide stronger profile models while unknown schemas pass through intact.

    Args:
        schema: Versioned schema identifier, such as ``im.message.v1``.
        data: Schema-owned payload data.

    Raises:
        ValueError: If the schema identifier is empty.
    """

    schema: str
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the envelope while leaving its data uninterpreted.

        Raises:
            ValueError: If the schema identifier is empty.
        """
        if not self.schema or not self.schema.strip():
            raise ValueError("payload schema must not be empty")

"""Outbound command and result models."""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from ..errors import GatewayError
from .endpoint import EndpointRef
from .payload import Payload

CommandStatus = Literal["accepted", "success", "failed"]


@dataclass(slots=True, kw_only=True)
class GatewayCommand:
    """Represent an operation requested against a target endpoint.

    Args:
        target: Endpoint that should receive the command.
        type: Adapter-defined command type.
        payload: Extensible command payload.
        id: Stable command identifier.
        metadata: Transport metadata not represented by the payload profile.
        correlation_id: Optional correlation identifier.

    Raises:
        ValueError: If the command identifier or type is empty.
    """

    target: EndpointRef
    type: str
    payload: Payload
    id: str = field(default_factory=lambda: f"cmd_{uuid.uuid4().hex}")
    metadata: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        """Validate transport-level command invariants.

        Raises:
            ValueError: If the command identifier or type is empty.
        """
        if not self.id or not self.id.strip():
            raise ValueError("command id must not be empty")
        if not self.type or not self.type.strip():
            raise ValueError("command type must not be empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandResult:
    """Describe adapter command execution without exposing exceptions.

    Args:
        command_id: Identifier of the command being reported.
        status: Accepted, successful, or failed status.
        external_id: Optional platform or device result identifier.
        error: Stable error payload when execution failed.

    Raises:
        ValueError: If the result is internally inconsistent.
    """

    command_id: str
    status: CommandStatus
    external_id: str | None = None
    error: GatewayError | None = None

    def __post_init__(self) -> None:
        """Validate result consistency.

        Raises:
            ValueError: If the result is internally inconsistent.
        """
        if not self.command_id or not self.command_id.strip():
            raise ValueError("command result id must not be empty")
        if self.status not in {"accepted", "success", "failed"}:
            raise ValueError(f"unsupported command status: {self.status}")
        if self.status == "failed" and self.error is None:
            raise ValueError("failed command result must include an error")
        if self.status != "failed" and self.error is not None:
            raise ValueError("non-failed command result must not include an error")

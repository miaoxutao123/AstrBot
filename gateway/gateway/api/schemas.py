"""Pydantic request schemas at the network boundary."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from gateway.core import EndpointRef, GatewayCommand, Payload


class EndpointRefRequest(BaseModel):
    """Validate an endpoint received over the API."""

    model_config = ConfigDict(extra="forbid")

    transport: str = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    endpoint_id: str = Field(min_length=1)

    def to_core(self) -> EndpointRef:
        """Create the Core endpoint model.

        Returns:
            Validated Core endpoint reference.
        """
        return EndpointRef(
            transport=self.transport,
            adapter_id=self.adapter_id,
            endpoint_id=self.endpoint_id,
        )


class PayloadRequest(BaseModel):
    """Validate an extensible payload envelope."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_name: str = Field(alias="schema", min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)

    def to_core(self) -> Payload:
        """Create the Core payload model.

        Returns:
            Validated Core payload.
        """
        return Payload(schema=self.schema_name, data=self.data)


class CommandRequest(BaseModel):
    """Validate a command submitted over HTTP."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, min_length=1)
    target: EndpointRefRequest
    type: str = Field(min_length=1)
    payload: PayloadRequest
    metadata: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None

    def to_core(self) -> GatewayCommand:
        """Create the Core command model.

        Returns:
            Validated Core command.
        """
        values: dict[str, Any] = {
            "target": self.target.to_core(),
            "type": self.type,
            "payload": self.payload.to_core(),
            "metadata": self.metadata,
            "correlation_id": self.correlation_id,
        }
        if self.id is not None:
            values["id"] = self.id
        return GatewayCommand(**values)

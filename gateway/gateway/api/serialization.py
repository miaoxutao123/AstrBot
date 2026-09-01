"""Explicit Core-to-wire serialization helpers."""

import base64
import binascii
import json
from typing import Any

from gateway.core import (
    AdapterRuntimeInfo,
    Capability,
    CommandResult,
    EndpointRef,
    GatewayError,
    GatewayEvent,
)


def endpoint_to_dict(endpoint: EndpointRef) -> dict[str, str]:
    """Serialize an endpoint.

    Args:
        endpoint: Core endpoint reference.

    Returns:
        JSON-compatible endpoint mapping.
    """
    return {
        "family": endpoint.family,
        "adapter_type": endpoint.adapter_type,
        "adapter_id": endpoint.adapter_id,
        "endpoint_id": endpoint.endpoint_id,
    }


def endpoint_resource_id(endpoint: EndpointRef) -> str:
    """Create a URL-safe opaque endpoint resource identifier.

    Args:
        endpoint: Core endpoint reference.

    Returns:
        Unpadded URL-safe base64 identifier.
    """
    raw = json.dumps(
        [
            endpoint.family,
            endpoint.adapter_type,
            endpoint.adapter_id,
            endpoint.endpoint_id,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def endpoint_from_resource_id(resource_id: str) -> EndpointRef:
    """Decode a URL-safe endpoint resource identifier.

    Args:
        resource_id: Identifier returned by the endpoints API.

    Returns:
        Decoded Core endpoint reference.

    Raises:
        ValueError: If the identifier is malformed.
    """
    padding = "=" * (-len(resource_id) % 4)
    try:
        raw = base64.b64decode(
            resource_id + padding,
            altchars=b"-_",
            validate=True,
        )
        values = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid endpoint resource id") from exc
    if (
        not isinstance(values, list)
        or len(values) != 4
        or not all(isinstance(value, str) for value in values)
    ):
        raise ValueError("invalid endpoint resource id")
    return EndpointRef(values[0], values[1], values[2], values[3])


def error_to_dict(error: GatewayError) -> dict[str, Any]:
    """Serialize a stable Gateway error.

    Args:
        error: Core error.

    Returns:
        JSON-compatible error mapping.
    """
    return {
        "code": error.code.value,
        "message": error.message,
        "retryable": error.retryable,
        "details": error.details,
    }


def event_to_dict(event: GatewayEvent) -> dict[str, Any]:
    """Serialize a Gateway event.

    Args:
        event: Core event.

    Returns:
        JSON-compatible event mapping.
    """
    return {
        "id": event.id,
        "source": endpoint_to_dict(event.source),
        "type": event.type,
        "payload": {
            "schema": event.payload.schema,
            "data": event.payload.data,
        },
        "timestamp": event.timestamp,
        "metadata": event.metadata,
        "correlation_id": event.correlation_id,
    }


def command_result_to_dict(result: CommandResult) -> dict[str, Any]:
    """Serialize a command result.

    Args:
        result: Core command result.

    Returns:
        JSON-compatible result mapping.
    """
    return {
        "command_id": result.command_id,
        "status": result.status,
        "external_id": result.external_id,
        "error": error_to_dict(result.error) if result.error is not None else None,
    }


def capability_to_dict(capability: Capability) -> dict[str, Any]:
    """Serialize a capability.

    Args:
        capability: Core capability.

    Returns:
        JSON-compatible capability mapping.
    """
    return {
        "name": capability.name,
        "version": capability.version,
        "schema": capability.schema,
    }


def runtime_info_to_dict(info: AdapterRuntimeInfo) -> dict[str, Any]:
    """Serialize adapter runtime information.

    Args:
        info: Core adapter runtime information.

    Returns:
        JSON-compatible adapter state mapping.
    """
    return {
        "id": info.adapter_id,
        "type": info.adapter_type,
        "family": info.family,
        "state": info.state.value,
        "reason": info.reason,
        "error": error_to_dict(info.error) if info.error is not None else None,
    }

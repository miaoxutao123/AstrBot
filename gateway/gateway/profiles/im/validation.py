"""Validation primitives shared by IM profile models."""

from collections.abc import Mapping
from typing import Any


def require_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    """Require a string-keyed mapping.

    Args:
        value: Untrusted profile value.
        field_name: Field name used in validation errors.

    Returns:
        Validated mapping.

    Raises:
        ValueError: If the value is not a mapping with string keys.
    """
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field_name} must be an object")
    return value


def require_string(value: object, field_name: str) -> str:
    """Require a non-empty string.

    Args:
        value: Untrusted profile value.
        field_name: Field name used in validation errors.

    Returns:
        Validated string.

    Raises:
        ValueError: If the value is empty or not a string.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def optional_string(value: object, field_name: str) -> str | None:
    """Validate an optional string.

    Args:
        value: Untrusted profile value.
        field_name: Field name used in validation errors.

    Returns:
        Validated string or ``None``.

    Raises:
        ValueError: If a present value is not a non-empty string.
    """
    return None if value is None else require_string(value, field_name)

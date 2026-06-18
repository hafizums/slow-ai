"""Schema helpers for node definitions and object_info output."""

from __future__ import annotations

from typing import Any, Mapping

from slow_ai.domain.exceptions import GraphValidationError


def validate_config_schema(
    node_type: str,
    config: Mapping[str, Any],
    schema: Mapping[str, Mapping[str, Any]],
) -> None:
    for fieldname, field_schema in schema.items():
        required = bool(field_schema.get("required", False))
        value = config.get(fieldname)
        if required and _is_empty(value):
            raise GraphValidationError(f"{node_type}.{fieldname} is required.")
        if _is_empty(value):
            continue

        expected_type = field_schema.get("value_type")
        if expected_type and not _matches_value_type(value, str(expected_type)):
            raise GraphValidationError(f"{node_type}.{fieldname} has invalid type.")

        allowed_values = field_schema.get("options")
        if allowed_values and value not in allowed_values:
            raise GraphValidationError(f"{node_type}.{fieldname} has invalid value: {value}")


def serialize_node_definition(node) -> dict[str, Any]:
    return {
        "type": node.type,
        "label": node.label,
        "category": node.category,
        "version": node.version,
        "is_output_node": bool(node.is_output_node),
        "input_schema": _plain_dict(node.input_schema()),
        "config_schema": _plain_dict(node.config_schema()),
        "output_schema": _plain_dict(node.output_schema()),
    }


def _is_empty(value: Any) -> bool:
    return value is None or value == ""


def _matches_value_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, Mapping)
    if expected_type == "array":
        return isinstance(value, (list, tuple))
    return True


def _plain_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _plain_value(item) for key, item in value.items()}


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain_value(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value

"""Template input schema validation and application."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import frappe

from slow_ai.application.assets import ALLOWED_ASSET_TYPES
from slow_ai.application.assets import view as view_asset


INPUT_TYPES = frozenset(
    {
        "TEXT",
        "LONG_TEXT",
        "NUMBER",
        "SELECT",
        "BOOLEAN",
        "ASSET",
        "IMAGE_ASSET",
        "VIDEO_ASSET",
        "AUDIO_ASSET",
    }
)
UNSAFE_TARGET_FIELDS = frozenset(
    {
        "provider",
        "model",
        "provider_account",
        "api_key",
        "api_key_secret",
        "request_json",
        "response_json",
        "raw_error_json",
    }
)
LEGACY_EDITABLE_FIELDS = {
    "text_prompt": frozenset({"text"}),
    "upload_asset": frozenset({"asset", "asset_type"}),
}


def normalize_input_schema(input_schema: Any, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a canonical, safe template input schema."""

    raw_schema = _loads_json(input_schema, [])
    if not raw_schema:
        return []
    if isinstance(raw_schema, Mapping):
        raw_schema = raw_schema.get("inputs", [])
    if not isinstance(raw_schema, list):
        frappe.throw("Template input_schema_json must be a JSON list or an object with an inputs list.")

    nodes_by_id = _nodes_by_id(nodes)
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_field in enumerate(raw_schema):
        if not isinstance(raw_field, Mapping):
            frappe.throw(f"Template input schema entry {index + 1} must be an object.")
        field_id = _field_identifier(raw_field.get("id") or raw_field.get("fieldname"), "input id")
        if field_id in seen_ids:
            frappe.throw(f"Duplicate template input id: {field_id}")
        seen_ids.add(field_id)

        input_type = _normalize_input_type(raw_field.get("input_type") or raw_field.get("type"))
        target_node_id = _field_identifier(
            raw_field.get("target_node_id") or raw_field.get("node_id"),
            f"{field_id}.target_node_id",
        )
        target_config_field = _target_config_field(
            raw_field.get("target_config_field") or raw_field.get("config_field"),
            field_id,
        )
        target_node = nodes_by_id.get(target_node_id)
        if not target_node:
            frappe.throw(f"Template input target node does not exist: {target_node_id}")
        target_config = target_node.get("config") or {}
        if target_config_field not in target_config:
            frappe.throw(f"Template input target config field does not exist: {target_node_id}.{target_config_field}")

        field: dict[str, Any] = {
            "id": field_id,
            "label": str(raw_field.get("label") or field_id),
            "input_type": input_type,
            "target_node_id": target_node_id,
            "target_config_field": target_config_field,
            "required": bool(raw_field.get("required", False)),
        }
        for optional_key in ("help", "description", "placeholder", "example"):
            if raw_field.get(optional_key) not in (None, ""):
                field[optional_key] = str(raw_field.get(optional_key))
        if "default" in raw_field:
            field["default"] = _validate_scalar_default(input_type, raw_field.get("default"), raw_field)
        if input_type == "SELECT":
            field["options"] = _normalize_options(raw_field.get("options"), field_id)
        if input_type == "NUMBER":
            if raw_field.get("min") not in (None, ""):
                field["min"] = _decimal_string(raw_field.get("min"), f"{field_id}.min")
            if raw_field.get("max") not in (None, ""):
                field["max"] = _decimal_string(raw_field.get("max"), f"{field_id}.max")
            if "min" in field and "max" in field and Decimal(field["min"]) > Decimal(field["max"]):
                frappe.throw(f"Template input min cannot exceed max: {field_id}")
        if input_type.endswith("ASSET"):
            field["accepted_asset_types"] = _accepted_asset_types(input_type, raw_field.get("accepted_asset_types"))
        if isinstance(raw_field.get("ui"), Mapping):
            field["ui"] = dict(raw_field.get("ui"))
        normalized.append(field)
    return normalized


def apply_input_values(
    *,
    nodes: list[dict[str, Any]],
    input_schema: list[dict[str, Any]],
    values: Any,
    project: str,
) -> list[dict[str, Any]]:
    """Validate schema values and apply them to allowed node config fields."""

    submitted = _loads_json(values, {})
    if submitted is None:
        submitted = {}
    if not isinstance(submitted, Mapping):
        frappe.throw("Template input values must be a JSON object.")
    allowed_ids = {field["id"] for field in input_schema}
    extra_ids = sorted(str(key) for key in submitted if str(key) not in allowed_ids)
    if extra_ids:
        frappe.throw(f"Unknown template input value: {extra_ids[0]}")

    patched_nodes = _copy_nodes(nodes)
    patched_by_id = _nodes_by_id(patched_nodes)
    for field in input_schema:
        raw_value = submitted.get(field["id"])
        if raw_value in (None, "") and "default" in field:
            raw_value = field["default"]
        if raw_value in (None, ""):
            if field.get("required"):
                frappe.throw(f"Required template input is missing: {field['id']}")
            continue

        value, asset_payload = _normalize_value(field, raw_value, project)
        node = patched_by_id[field["target_node_id"]]
        node_config = dict(node.get("config") or {})
        node_config[field["target_config_field"]] = value
        if asset_payload and field["target_config_field"] == "asset" and "asset_type" in node_config:
            node_config["asset_type"] = asset_payload.get("asset_type")
        node["config"] = node_config
    return patched_nodes


def extract_input_values_from_nodes(
    *,
    nodes: list[dict[str, Any]],
    input_schema: list[dict[str, Any]],
) -> dict[str, Any]:
    """Extract previous values only through declared safe template input fields."""

    nodes_by_id = _nodes_by_id(_copy_nodes(nodes))
    values: dict[str, Any] = {}
    for field in input_schema:
        node = nodes_by_id.get(str(field.get("target_node_id") or ""))
        if not node:
            continue
        config = node.get("config") or {}
        target_field = str(field.get("target_config_field") or "")
        if target_field not in config:
            continue
        value = config.get(target_field)
        if value is not None:
            values[str(field["id"])] = value
    return values


def apply_legacy_public_tool_values(
    *,
    nodes: list[dict[str, Any]],
    values: Any,
    project: str,
) -> list[dict[str, Any]]:
    """Apply the older node-derived public tool form values with a fixed allow-list."""

    submitted = _loads_json(values, {})
    if submitted is None:
        submitted = {}
    if not isinstance(submitted, Mapping):
        frappe.throw("Public tool form values must be a JSON object.")
    patched_nodes = _copy_nodes(nodes)
    patched_by_id = _nodes_by_id(patched_nodes)
    for node_id, node_values in submitted.items():
        node = patched_by_id.get(str(node_id))
        if not node:
            frappe.throw(f"Unknown public tool node: {node_id}")
        if not isinstance(node_values, Mapping):
            frappe.throw(f"Public tool node values must be an object: {node_id}")
        allowed_fields = LEGACY_EDITABLE_FIELDS.get(node.get("type"), frozenset())
        for field_name, raw_value in node_values.items():
            field_name = str(field_name)
            _target_config_field(field_name, str(node_id))
            if field_name not in allowed_fields:
                frappe.throw(f"Public tool field is not editable: {node_id}.{field_name}")
            config = dict(node.get("config") or {})
            if field_name == "asset" and raw_value:
                asset = view_asset(str(raw_value))
                config["asset"] = asset["name"]
                if "asset_type" in config:
                    config["asset_type"] = asset["asset_type"]
            elif field_name == "asset_type" and raw_value:
                asset_type = str(raw_value).upper()
                if asset_type not in ALLOWED_ASSET_TYPES:
                    frappe.throw(f"Unsupported AI Asset type: {raw_value}")
                config["asset_type"] = asset_type
            else:
                config[field_name] = str(raw_value or "")
            node["config"] = config
    return patched_nodes


def _normalize_value(field: Mapping[str, Any], raw_value: Any, project: str) -> tuple[Any, dict[str, Any] | None]:
    input_type = field["input_type"]
    if input_type in {"TEXT", "LONG_TEXT"}:
        return str(raw_value), None
    if input_type == "NUMBER":
        number = _to_decimal(raw_value, field["id"])
        if field.get("min") is not None and number < Decimal(str(field["min"])):
            frappe.throw(f"Template input is below minimum: {field['id']}")
        if field.get("max") is not None and number > Decimal(str(field["max"])):
            frappe.throw(f"Template input is above maximum: {field['id']}")
        return int(number) if number == number.to_integral_value() else float(number), None
    if input_type == "SELECT":
        value = str(raw_value)
        options = {str(option["value"]) for option in field.get("options", [])}
        if value not in options:
            frappe.throw(f"Template input option is invalid: {field['id']}")
        return value, None
    if input_type == "BOOLEAN":
        return _to_bool(raw_value), None
    if input_type.endswith("ASSET"):
        asset = view_asset(str(raw_value))
        accepted = set(field.get("accepted_asset_types") or [])
        if asset["asset_type"] not in accepted:
            frappe.throw(f"Template input asset type is invalid: {field['id']}")
        return asset["name"], asset
    frappe.throw(f"Unsupported template input type: {input_type}")


def _validate_scalar_default(input_type: str, value: Any, raw_field: Mapping[str, Any]) -> Any:
    if value in (None, ""):
        return value
    if input_type in {"TEXT", "LONG_TEXT", "SELECT"}:
        return str(value)
    if input_type == "NUMBER":
        return _decimal_string(value, str(raw_field.get("id") or "default"))
    if input_type == "BOOLEAN":
        return _to_bool(value)
    if input_type.endswith("ASSET"):
        return str(value)
    return value


def _normalize_input_type(value: Any) -> str:
    normalized = str(value or "").strip().upper().replace("-", "_")
    aliases = {
        "TEXTAREA": "LONG_TEXT",
        "LONGTEXT": "LONG_TEXT",
        "CHECK": "BOOLEAN",
        "CHECKBOX": "BOOLEAN",
        "IMAGE": "IMAGE_ASSET",
        "VIDEO": "VIDEO_ASSET",
        "AUDIO": "AUDIO_ASSET",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in INPUT_TYPES:
        frappe.throw(f"Unsupported template input type: {value}")
    return normalized


def _field_identifier(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        frappe.throw(f"Template input {label} is required.")
    if not re.match(r"^[A-Za-z0-9_.:-]+$", text):
        frappe.throw(f"Template input {label} contains unsupported characters.")
    return text


def _target_config_field(value: Any, field_id: str) -> str:
    text = _field_identifier(value, f"{field_id}.target_config_field")
    lowered = text.lower()
    if lowered in UNSAFE_TARGET_FIELDS or "api_key" in lowered:
        frappe.throw(f"Template input target field is not allowed: {text}")
    return text


def _normalize_options(options: Any, field_id: str) -> list[dict[str, str]]:
    if not isinstance(options, list) or not options:
        frappe.throw(f"Template input SELECT requires options: {field_id}")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for option in options:
        if isinstance(option, Mapping):
            value = str(option.get("value") or "").strip()
            label = str(option.get("label") or value).strip()
        else:
            value = str(option or "").strip()
            label = value
        if not value:
            frappe.throw(f"Template input option value is required: {field_id}")
        if value in seen:
            frappe.throw(f"Duplicate template input option: {field_id}.{value}")
        seen.add(value)
        normalized.append({"value": value, "label": label})
    return normalized


def _accepted_asset_types(input_type: str, value: Any) -> list[str]:
    if input_type == "IMAGE_ASSET":
        return ["IMAGE"]
    if input_type == "VIDEO_ASSET":
        return ["VIDEO"]
    if input_type == "AUDIO_ASSET":
        return ["AUDIO"]
    raw_types = value or sorted(ALLOWED_ASSET_TYPES)
    if not isinstance(raw_types, list) or not raw_types:
        frappe.throw("ASSET template inputs require accepted_asset_types.")
    normalized = sorted({str(asset_type).upper() for asset_type in raw_types})
    unsupported = [asset_type for asset_type in normalized if asset_type not in ALLOWED_ASSET_TYPES]
    if unsupported:
        frappe.throw(f"Unsupported template input asset type: {unsupported[0]}")
    return normalized


def _decimal_string(value: Any, label: str) -> str:
    return str(_to_decimal(value, label))


def _to_decimal(value: Any, label: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        frappe.throw(f"Template input value must be numeric: {label}")


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    frappe.throw("Template input value must be boolean.")


def _nodes_by_id(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(node.get("id")): node for node in nodes if node.get("id")}


def _copy_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return json.loads(json.dumps(nodes))


def _loads_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (list, tuple)):
        return list(value)
    return value

"""Shared helpers for safe API/display payloads.

These helpers are deterministic and side-effect-free. Callers may provide a
read-only asset existence callback when they want output summaries to include
only persisted AI Asset names.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Mapping


SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[_-]?key|authorization|bearer|secret|token|password|provider_account|request_json|response_json|raw_error_json|raw|url)",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
KEY_VALUE_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|secret|token|password)\b\s*[:=]\s*[^,\s}]+"
)


def is_sensitive_key(key: Any) -> bool:
    return bool(SENSITIVE_KEY_PATTERN.search(str(key or "")))


def redact_text(value: Any, *, limit: int = 240) -> str:
    text = str(value or "")
    text = BEARER_PATTERN.sub("Bearer [redacted]", text)
    text = KEY_VALUE_SECRET_PATTERN.sub("[redacted]", text)
    text = URL_PATTERN.sub("[link hidden]", text)
    return text[:limit]


def safe_metadata(value: Any, *, text_limit: int = 500) -> Any:
    if isinstance(value, Mapping):
        safe = {}
        for key, child in value.items():
            key_text = str(key)
            if is_sensitive_key(key_text):
                continue
            safe[key_text] = safe_metadata(child, text_limit=text_limit)
        return safe
    if isinstance(value, (list, tuple)):
        return [safe_metadata(child, text_limit=text_limit) for child in value]
    if isinstance(value, str):
        return redact_text(value, limit=text_limit)
    return value


def safe_error_message(value: Any, fallback: str | None = None, *, limit: int = 240) -> str | None:
    payload = loads_json(value, None)
    if payload is None:
        return fallback
    if isinstance(payload, str):
        return redact_text(payload, limit=limit) or fallback
    if isinstance(payload, Mapping):
        for key in ("message", "error", "status", "code", "type"):
            candidate = payload.get(key)
            if candidate is None or isinstance(candidate, (Mapping, list, tuple)):
                continue
            message = redact_text(candidate, limit=limit)
            if message:
                return message
    return fallback or "Error details captured on server."


def safe_error_payload(value: Any) -> dict[str, str] | None:
    payload = loads_json(value, None)
    if payload is None:
        return None
    message = safe_error_message(value, "Error details captured on server.")
    safe: dict[str, str] = {"message": message or "Error details captured on server."}
    if isinstance(payload, Mapping):
        for key in ("code", "status", "type"):
            candidate = payload.get(key)
            if candidate is None or isinstance(candidate, (Mapping, list, tuple)):
                continue
            sanitized = redact_text(candidate)
            if sanitized:
                safe[key] = sanitized
    return safe


def safe_node_output_summary(value: Any, *, asset_exists: Callable[[str], bool] | None = None) -> dict[str, Any]:
    payload = loads_json(value, None)
    if payload is None:
        return {"has_output": False, "asset_names": [], "keys": []}
    return {
        "has_output": True,
        "asset_names": asset_names_from_value(payload, asset_exists=asset_exists),
        "keys": safe_top_level_output_keys(payload),
    }


def safe_top_level_output_keys(value: Any, *, limit: int = 10) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    keys = [str(key) for key in value if not is_sensitive_key(key)]
    return sorted(keys)[:limit]


def asset_names_from_value(value: Any, *, asset_exists: Callable[[str], bool] | None = None) -> list[str]:
    names: set[str] = set()
    _collect_asset_names(value, names, asset_exists=asset_exists)
    return sorted(names)


def loads_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _collect_asset_names(value: Any, names: set[str], *, asset_exists: Callable[[str], bool] | None) -> None:
    if isinstance(value, str) and value.startswith("AI-ASSET-"):
        if asset_exists is None or asset_exists(value):
            names.add(value)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_asset_names(item, names, asset_exists=asset_exists)
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if is_sensitive_key(key):
                continue
            if key in {"asset", "asset_name", "asset_names"}:
                _collect_asset_names(child, names, asset_exists=asset_exists)
                continue
            _collect_asset_names(child, names, asset_exists=asset_exists)

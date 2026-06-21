"""Asset application services."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

import frappe

from slow_ai.application.project_access import assert_can_edit_project, assert_can_view_project
from slow_ai.infrastructure.provider_outputs import AssetWriter


ALLOWED_ASSET_TYPES = frozenset({"IMAGE", "VIDEO", "AUDIO", "MASK", "JSON", "TEXT"})
SENSITIVE_METADATA_KEY_PATTERN = re.compile(
    r"(api[_-]?key|authorization|bearer|secret|token|password|provider_account|request_json|response_json|raw_error_json|raw|url)",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
KEY_VALUE_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|secret|token|password)\b\s*[:=]\s*[^,\s}]+"
)


def upload(
    *,
    project: str,
    asset_type: str,
    url: str | None = None,
    file: str | None = None,
    mime_type: str | None = None,
    metadata: Any | None = None,
) -> dict[str, Any]:
    normalized_asset_type = asset_type.upper()
    if normalized_asset_type not in ALLOWED_ASSET_TYPES:
        frappe.throw(f"Unsupported AI Asset type: {asset_type}")
    if not url and not file:
        frappe.throw("Either url or file is required for AI Asset upload.")
    assert_can_edit_project(project)

    asset_name = AssetWriter().create_uploaded_asset(
        project_name=project,
        asset_type=normalized_asset_type,
        url=url,
        file=file,
        mime_type=mime_type,
        metadata=_loads_json(metadata, {}),
    )
    return view(asset_name)


def view(asset: str, ignore_project_permissions: bool = False) -> dict[str, Any]:
    doc = frappe.get_doc("AI Asset", asset)
    if not ignore_project_permissions:
        assert_can_view_project(doc.project)
    return {
        "name": doc.name,
        "project": doc.project,
        "asset_type": doc.asset_type,
        "file": doc.file,
        "url": doc.url,
        "mime_type": doc.mime_type,
        "width": doc.width,
        "height": doc.height,
        "duration_seconds": doc.duration_seconds,
        "source_workflow_run": doc.source_workflow_run,
        "source_node_run": doc.source_node_run,
        "source_provider_job": doc.source_provider_job,
        "created": doc.creation,
        "modified": doc.modified,
        "metadata": _safe_metadata(_loads_json(doc.metadata_json, {})),
    }


def _loads_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _safe_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe = {}
        for key, child in value.items():
            key_text = str(key)
            if SENSITIVE_METADATA_KEY_PATTERN.search(key_text):
                continue
            safe[key_text] = _safe_metadata(child)
        return safe
    if isinstance(value, list):
        return [_safe_metadata(child) for child in value]
    if isinstance(value, tuple):
        return [_safe_metadata(child) for child in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _sanitize_text(value: str) -> str:
    text = str(value or "")
    text = BEARER_PATTERN.sub("Bearer [redacted]", text)
    text = KEY_VALUE_SECRET_PATTERN.sub("[redacted]", text)
    text = URL_PATTERN.sub("[link hidden]", text)
    return text[:500]

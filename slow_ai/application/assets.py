"""Asset application services."""

from __future__ import annotations

import json
from typing import Any, Mapping

import frappe

from slow_ai.infrastructure.provider_outputs import AssetWriter


ALLOWED_ASSET_TYPES = frozenset({"IMAGE", "VIDEO", "AUDIO", "MASK", "JSON", "TEXT"})


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

    asset_name = AssetWriter().create_uploaded_asset(
        project_name=project,
        asset_type=normalized_asset_type,
        url=url,
        file=file,
        mime_type=mime_type,
        metadata=_loads_json(metadata, {}),
    )
    return view(asset_name)


def view(asset: str) -> dict[str, Any]:
    doc = frappe.get_doc("AI Asset", asset)
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
        "metadata": _loads_json(doc.metadata_json, {}),
    }


def _loads_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, Mapping):
        return dict(value)
    return value

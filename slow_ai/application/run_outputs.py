"""Safe run output gallery payloads."""

from __future__ import annotations

import json
from typing import Any, Mapping

import frappe

from slow_ai.application.assets import view as view_asset
from slow_ai.application.project_access import assert_can_view_project
from slow_ai.application.template_lineage import safe_template_lineage


def get_run_output_gallery(
    workflow_run: str,
    selected_assets: Any | None = None,
    include_unselected: bool = True,
    ignore_project_permissions: bool = False,
) -> dict[str, Any]:
    """Return safe grouped asset outputs for one workflow run."""

    run = frappe.get_doc("AI Workflow Run", workflow_run)
    if not ignore_project_permissions:
        assert_can_view_project(run.project)

    selected = set(_normalize_selected_assets(selected_assets))
    node_runs = _node_runs_for_gallery(run.name)
    node_run_by_name = {row["name"]: row for row in node_runs}
    discovered = _discover_output_assets(run.name, node_runs)
    if selected and not include_unselected:
        discovered = [item for item in discovered if item["asset_name"] in selected]

    groups: dict[str, dict[str, Any]] = {}
    flat_assets: list[dict[str, Any]] = []
    for item in discovered:
        asset_name = item["asset_name"]
        if not frappe.db.exists("AI Asset", asset_name):
            continue
        asset = _safe_gallery_asset(
            view_asset(asset_name, ignore_project_permissions=ignore_project_permissions),
            selected=asset_name in selected,
            shareable=run.status == "SUCCEEDED",
            source_output=item.get("source_output"),
        )
        node_run = node_run_by_name.get(asset.get("source_node_run") or item.get("source_node_run"))
        group_id = f"node:{node_run['name']}" if node_run else "run:outputs"
        if group_id not in groups:
            groups[group_id] = _new_group(group_id, node_run)
        groups[group_id]["assets"].append(asset)
        flat_assets.append(asset)

    return {
        "run": _run_metadata(run.as_dict()),
        "groups": list(groups.values()),
        "assets": flat_assets,
        "selected_assets": sorted(selected),
    }


def _run_metadata(row) -> dict[str, Any]:
    workflow = row.get("workflow")
    return {
        "workflow_run": row.get("name"),
        "workflow": workflow,
        "workflow_title": frappe.db.get_value("AI Workflow", workflow, "title") if workflow else None,
        "project": row.get("project"),
        "status": row.get("status"),
        "queued_at": row.get("queued_at"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "created": row.get("creation"),
        "modified": row.get("modified"),
        "template_lineage": safe_template_lineage(
            row.get("source_template"),
            row.get("source_template_version"),
        ),
    }


def _node_runs_for_gallery(workflow_run: str) -> list[dict[str, Any]]:
    rows = frappe.get_all(
        "AI Node Run",
        filters={"workflow_run": workflow_run},
        fields=["name", "node_id", "node_type", "output_json", "creation", "modified"],
        order_by="creation asc",
    )
    return [dict(row) for row in rows]


def _discover_output_assets(workflow_run: str, node_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    seen: set[str] = set()

    rows = frappe.get_all(
        "AI Asset",
        filters={"source_workflow_run": workflow_run},
        fields=["name", "source_node_run"],
        order_by="creation asc",
    )
    for row in rows:
        _add_asset(
            discovered,
            seen,
            asset_name=row.name,
            source_node_run=row.source_node_run,
            source_output=None,
        )

    for node_run in node_runs:
        for match in _asset_refs_from_value(_loads_json(node_run.get("output_json"), {})):
            _add_asset(
                discovered,
                seen,
                asset_name=match["asset_name"],
                source_node_run=node_run["name"],
                source_output=match.get("source_output"),
            )
    return discovered


def _add_asset(
    discovered: list[dict[str, Any]],
    seen: set[str],
    *,
    asset_name: str,
    source_node_run: str | None,
    source_output: str | None,
) -> None:
    if not asset_name or asset_name in seen:
        return
    discovered.append(
        {
            "asset_name": asset_name,
            "source_node_run": source_node_run,
            "source_output": source_output,
        }
    )
    seen.add(asset_name)


def _new_group(group_id: str, node_run: Mapping[str, Any] | None) -> dict[str, Any]:
    if not node_run:
        return {
            "group_id": group_id,
            "label": "Run Outputs",
            "source_node_run": None,
            "source_node_id": None,
            "source_node_type": None,
            "assets": [],
        }
    return {
        "group_id": group_id,
        "label": node_run.get("node_id") or node_run.get("name"),
        "source_node_run": node_run.get("name"),
        "source_node_id": node_run.get("node_id"),
        "source_node_type": node_run.get("node_type"),
        "assets": [],
    }


def _safe_gallery_asset(
    asset: Mapping[str, Any],
    *,
    selected: bool,
    shareable: bool,
    source_output: str | None,
) -> dict[str, Any]:
    return {
        "name": asset.get("name"),
        "asset_type": asset.get("asset_type"),
        "mime_type": asset.get("mime_type"),
        "file": asset.get("file"),
        "url": asset.get("url"),
        "width": asset.get("width"),
        "height": asset.get("height"),
        "duration_seconds": asset.get("duration_seconds"),
        "source_workflow_run": asset.get("source_workflow_run"),
        "source_node_run": asset.get("source_node_run"),
        "source_provider_job": asset.get("source_provider_job"),
        "source_output": source_output,
        "created": asset.get("created"),
        "modified": asset.get("modified"),
        "metadata": asset.get("metadata") or {},
        "selected": selected,
        "shareable": shareable,
    }


def _asset_refs_from_value(value: Any, source_output: str | None = None) -> list[dict[str, str | None]]:
    refs: list[dict[str, str | None]] = []
    if isinstance(value, str) and value.startswith("AI-ASSET-"):
        refs.append({"asset_name": value, "source_output": source_output})
        return refs
    if isinstance(value, (list, tuple)):
        for item in value:
            refs.extend(_asset_refs_from_value(item, source_output=source_output))
        return refs
    if isinstance(value, dict):
        for key, item in value.items():
            child_output = str(key) if source_output is None else source_output
            refs.extend(_asset_refs_from_value(item, source_output=child_output))
    return refs


def _normalize_selected_assets(value: Any | None) -> list[str]:
    parsed = _loads_json(value, value)
    if isinstance(parsed, str):
        parsed = [parsed]
    if not isinstance(parsed, (list, tuple)):
        return []

    selected: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        asset_name = str(item or "").strip()
        if not asset_name or asset_name in seen:
            continue
        selected.append(asset_name)
        seen.add(asset_name)
    return selected


def _loads_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default
    return value

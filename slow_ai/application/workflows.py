"""Workflow draft application services."""

from __future__ import annotations

import json
from typing import Any, Mapping

import frappe
from frappe.utils import now_datetime

from slow_ai.application.project_access import assert_can_edit_project, assert_can_view_project
from slow_ai.application.safe_payloads import is_sensitive_key
from slow_ai.application.template_lineage import assert_valid_template_lineage
from slow_ai.application.template_lineage import safe_template_lineage
from slow_ai.application.workflow_validation import validate_workflow
from slow_ai.domain.exceptions import GraphValidationError
from slow_ai.domain.snapshots import canonical_json


def save_workflow(
    *,
    project: str,
    title: str,
    nodes: Any,
    edges: Any,
    layout: Any | None = None,
    workflow: str | None = None,
    status: str = "DRAFT",
    source_template: str | None = None,
    source_template_version: str | None = None,
    is_temporary_tool_draft: bool | None = None,
    tool_draft_type: str | None = None,
    tool_draft_prepared_at: Any | None = None,
) -> dict[str, Any]:
    parsed_nodes = _loads_json(nodes, [])
    parsed_edges = _loads_json(edges, [])
    parsed_layout = _loads_json(layout, {})
    validate_workflow({"nodes": parsed_nodes, "edges": parsed_edges})
    _assert_safe_workflow_config(parsed_nodes)
    assert_can_edit_project(project)
    assert_valid_template_lineage(source_template, source_template_version)

    values = {
        "title": title,
        "project": project,
        "status": status,
        "draft_nodes_json": canonical_json(parsed_nodes),
        "draft_edges_json": canonical_json(parsed_edges),
        "layout_json": canonical_json(parsed_layout),
    }
    if source_template or source_template_version:
        values["source_template"] = source_template
        values["source_template_version"] = source_template_version
    if is_temporary_tool_draft is not None:
        values["is_temporary_tool_draft"] = 1 if is_temporary_tool_draft else 0
        values["tool_draft_type"] = _normalize_tool_draft_type(tool_draft_type)
        values["tool_draft_prepared_at"] = tool_draft_prepared_at or now_datetime()
    if workflow:
        doc = frappe.get_doc("AI Workflow", workflow)
        assert_can_edit_project(doc.project)
        doc.update(values)
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({"doctype": "AI Workflow", **values}).insert(ignore_permissions=True)

    return get_workflow(doc.name)


def get_workflow(workflow: str) -> dict[str, Any]:
    doc = frappe.get_doc("AI Workflow", workflow)
    assert_can_view_project(doc.project)
    return {
        "name": doc.name,
        "title": doc.title,
        "project": doc.project,
        "status": doc.status,
        "current_version": doc.current_version,
        "nodes": _safe_workflow_nodes(_loads_json(doc.draft_nodes_json, [])),
        "edges": _loads_json(doc.draft_edges_json, []),
        "layout": _loads_json(doc.layout_json, {}),
        "source_template": getattr(doc, "source_template", None),
        "source_template_version": getattr(doc, "source_template_version", None),
        "is_temporary_tool_draft": 1 if getattr(doc, "is_temporary_tool_draft", 0) else 0,
        "tool_draft_type": getattr(doc, "tool_draft_type", None),
        "tool_draft_prepared_at": getattr(doc, "tool_draft_prepared_at", None),
        "template_lineage": safe_template_lineage(
            getattr(doc, "source_template", None),
            getattr(doc, "source_template_version", None),
        ),
        "modified": doc.modified,
    }


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


def _normalize_tool_draft_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = str(value).strip().upper()
    if normalized not in {"PREPARED", "RERUN"}:
        frappe.throw(f"Unsupported public tool draft type: {value}.", frappe.ValidationError)
    return normalized


def _assert_safe_workflow_config(nodes: Any) -> None:
    for node in nodes if isinstance(nodes, list) else []:
        node_id = node.get("id") if isinstance(node, Mapping) else None
        config = node.get("config") if isinstance(node, Mapping) else None
        _assert_safe_config_value(config, path=str(node_id or "node"))


def _assert_safe_config_value(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if is_sensitive_key(key_text) and key_text != "provider_account":
                raise GraphValidationError(f"Workflow node config contains forbidden field: {child_path}")
            _assert_safe_config_value(child, path=child_path)
        return
    if isinstance(value, (list, tuple)):
        for idx, child in enumerate(value):
            _assert_safe_config_value(child, path=f"{path}[{idx}]")


def _safe_workflow_nodes(nodes: Any) -> Any:
    if isinstance(nodes, list):
        return [_safe_workflow_node(node) for node in nodes]
    return nodes


def _safe_workflow_node(node: Any) -> Any:
    if not isinstance(node, Mapping):
        return node
    safe = dict(node)
    safe["config"] = _safe_config_value(safe.get("config") or {})
    return safe


def _safe_config_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe = {}
        for key, child in value.items():
            key_text = str(key)
            if is_sensitive_key(key_text):
                continue
            safe[key_text] = _safe_config_value(child)
        return safe
    if isinstance(value, (list, tuple)):
        return [_safe_config_value(child) for child in value]
    return value

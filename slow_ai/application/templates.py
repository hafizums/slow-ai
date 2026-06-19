"""Workflow template application services."""

from __future__ import annotations

import json
from typing import Any, Mapping

import frappe

from slow_ai.application.workflow_validation import validate_workflow
from slow_ai.application.workflows import save_workflow
from slow_ai.domain.snapshots import canonical_json


TEMPLATE_STATUSES = frozenset({"DRAFT", "PUBLISHED", "ARCHIVED"})


def save_template(
    *,
    template_name: str,
    nodes: Any,
    edges: Any,
    layout: Any | None = None,
    template: str | None = None,
    status: str = "DRAFT",
    category: str | None = None,
    description: str | None = None,
    preview_asset: str | None = None,
) -> dict[str, Any]:
    parsed_nodes = _loads_json(nodes, [])
    parsed_edges = _loads_json(edges, [])
    parsed_layout = _loads_json(layout, {})
    normalized_status = status.upper()
    if normalized_status not in TEMPLATE_STATUSES:
        frappe.throw(f"Unsupported AI Workflow Template status: {status}")
    if normalized_status == "PUBLISHED":
        _require_system_manager("Publishing AI Workflow Templates requires System Manager.")
    validate_workflow({"nodes": parsed_nodes, "edges": parsed_edges})

    values = {
        "template_name": template_name,
        "status": normalized_status,
        "category": category,
        "description": description,
        "preview_asset": preview_asset,
        "nodes_json": canonical_json(parsed_nodes),
        "edges_json": canonical_json(parsed_edges),
        "layout_json": canonical_json(parsed_layout),
    }
    if template:
        doc = frappe.get_doc("AI Workflow Template", template)
        doc.update(values)
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({"doctype": "AI Workflow Template", **values}).insert(ignore_permissions=True)
    return get_template(doc.name)


def get_template(template: str) -> dict[str, Any]:
    doc = frappe.get_doc("AI Workflow Template", template)
    return {
        "name": doc.name,
        "template_name": doc.template_name,
        "status": doc.status,
        "category": doc.category,
        "description": doc.description,
        "preview_asset": doc.preview_asset,
        "nodes": _loads_json(doc.nodes_json, []),
        "edges": _loads_json(doc.edges_json, []),
        "layout": _loads_json(doc.layout_json, {}),
        "modified": doc.modified,
    }


def list_templates(status: str | None = None, category: str | None = None) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if status:
        filters["status"] = status.upper()
    if category:
        filters["category"] = category
    rows = frappe.get_all(
        "AI Workflow Template",
        filters=filters,
        fields=["name", "template_name", "status", "category", "description", "preview_asset", "modified"],
        order_by="modified desc",
    )
    return {"templates": [dict(row) for row in rows]}


def create_workflow_from_template(
    *,
    template: str,
    project: str,
    title: str | None = None,
) -> dict[str, Any]:
    template_doc = get_template(template)
    if template_doc["status"] == "ARCHIVED":
        frappe.throw(f"Cannot create workflow from archived template: {template}")
    return save_workflow(
        project=project,
        title=title or template_doc["template_name"],
        nodes=template_doc["nodes"],
        edges=template_doc["edges"],
        layout=template_doc["layout"],
        status="DRAFT",
    )


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


def _require_system_manager(message: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if "System Manager" not in frappe.get_roles(frappe.session.user):
        frappe.throw(message, frappe.PermissionError)

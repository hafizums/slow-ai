"""Workflow draft application services."""

from __future__ import annotations

import json
from typing import Any, Mapping

import frappe

from slow_ai.application.project_access import assert_can_edit_project, assert_can_view_project
from slow_ai.application.template_lineage import assert_valid_template_lineage
from slow_ai.application.template_lineage import safe_template_lineage
from slow_ai.application.workflow_validation import validate_workflow
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
) -> dict[str, Any]:
    parsed_nodes = _loads_json(nodes, [])
    parsed_edges = _loads_json(edges, [])
    parsed_layout = _loads_json(layout, {})
    validate_workflow({"nodes": parsed_nodes, "edges": parsed_edges})
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
        "nodes": _loads_json(doc.draft_nodes_json, []),
        "edges": _loads_json(doc.draft_edges_json, []),
        "layout": _loads_json(doc.layout_json, {}),
        "source_template": getattr(doc, "source_template", None),
        "source_template_version": getattr(doc, "source_template_version", None),
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

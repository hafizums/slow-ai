"""Workflow template application services."""

from __future__ import annotations

import json
from typing import Any, Mapping

import frappe
from frappe.utils import now_datetime

from slow_ai.application.workflow_validation import validate_workflow
from slow_ai.application.template_inputs import normalize_input_schema
from slow_ai.application.workflows import save_workflow
from slow_ai.domain.snapshots import canonical_json
from slow_ai.domain.snapshots import snapshot_hash


TEMPLATE_STATUSES = frozenset({"DRAFT", "IN_REVIEW", "PUBLISHED", "REJECTED", "ARCHIVED"})
OWNER_EDITABLE_STATUSES = frozenset({"DRAFT", "REJECTED"})
REVIEW_CONTROLLED_STATUSES = frozenset({"IN_REVIEW", "PUBLISHED", "ARCHIVED"})
TEMPLATE_VERSION_STATUSES = frozenset({"ACTIVE", "SUPERSEDED", "ROLLED_BACK", "ARCHIVED"})
FORBIDDEN_TEMPLATE_FRAGMENTS = (
    "api_key_secret",
    "Authorization: Bearer",
    "WAVESPEED_API_KEY",
    "REPLICATE_API_KEY",
    "api.wavespeed.ai",
    "wavespeed.ai/api",
    "api.replicate.com",
    "request_json",
    "response_json",
    "raw_error_json",
)
FORBIDDEN_NODE_CONFIG_KEYS = frozenset({"provider_account", "api_key_secret", "authorization", "secret", "token"})


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
    input_schema: Any | None = None,
    input_schema_json: Any | None = None,
) -> dict[str, Any]:
    parsed_nodes = _loads_json(nodes, [])
    parsed_edges = _loads_json(edges, [])
    parsed_layout = _loads_json(layout, {})
    normalized_status = status.upper()
    if normalized_status not in TEMPLATE_STATUSES:
        frappe.throw(f"Unsupported AI Workflow Template status: {status}")
    validate_workflow({"nodes": parsed_nodes, "edges": parsed_edges})
    normalized_input_schema = normalize_input_schema(
        input_schema if input_schema is not None else input_schema_json,
        parsed_nodes,
    )

    values = {
        "template_name": template_name,
        "status": normalized_status,
        "category": category,
        "description": description,
        "preview_asset": preview_asset,
        "nodes_json": canonical_json(parsed_nodes),
        "edges_json": canonical_json(parsed_edges),
        "layout_json": canonical_json(parsed_layout),
        "input_schema_json": canonical_json(normalized_input_schema),
    }
    if template:
        doc = frappe.get_doc("AI Workflow Template", template)
        _assert_can_edit_template(doc)
        _assert_save_status_allowed(normalized_status, doc)
        if doc.status == "PUBLISHED" and normalized_status == "DRAFT":
            values["status"] = "PUBLISHED"
        doc.update(values)
        doc.save(ignore_permissions=True)
    else:
        _assert_save_status_allowed(normalized_status, None)
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
        "input_schema": _loads_json(getattr(doc, "input_schema_json", None), []),
        "submitted_by": getattr(doc, "submitted_by", None),
        "submitted_at": getattr(doc, "submitted_at", None),
        "reviewed_by": getattr(doc, "reviewed_by", None),
        "reviewed_at": getattr(doc, "reviewed_at", None),
        "review_notes": getattr(doc, "review_notes", None),
        "rejection_reason": getattr(doc, "rejection_reason", None),
        "published_at": getattr(doc, "published_at", None),
        "published_version": getattr(doc, "published_version", None),
        "owner": doc.owner,
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
        fields=[
            "name",
            "template_name",
            "status",
            "category",
            "description",
            "preview_asset",
            "submitted_by",
            "submitted_at",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "rejection_reason",
            "published_at",
            "published_version",
            "owner",
            "modified",
        ],
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


def submit_template_for_review(template: str) -> dict[str, Any]:
    doc = frappe.get_doc("AI Workflow Template", template)
    _assert_can_submit_template(doc)
    if doc.status not in {"DRAFT", "REJECTED", "PUBLISHED"}:
        frappe.throw("Only DRAFT, REJECTED, or PUBLISHED templates can be submitted for review.", frappe.ValidationError)
    _validate_template_for_publication(doc)
    doc.status = "IN_REVIEW"
    doc.submitted_by = frappe.session.user
    doc.submitted_at = now_datetime()
    doc.reviewed_by = None
    doc.reviewed_at = None
    doc.review_notes = None
    doc.rejection_reason = None
    doc.save(ignore_permissions=True)
    return get_template(doc.name)


def approve_template(template: str, review_notes: str | None = None) -> dict[str, Any]:
    _require_system_manager("Approving AI Workflow Templates requires System Manager.")
    doc = frappe.get_doc("AI Workflow Template", template)
    if doc.status != "IN_REVIEW":
        frappe.throw("Only IN_REVIEW templates can be approved.", frappe.ValidationError)
    _validate_template_for_publication(doc)
    now = now_datetime()
    version = _create_template_version(doc, approved_by=frappe.session.user, approved_at=now, previous_active_status="SUPERSEDED")
    doc.status = "PUBLISHED"
    doc.reviewed_by = frappe.session.user
    doc.reviewed_at = now
    doc.review_notes = review_notes
    doc.rejection_reason = None
    doc.published_at = now
    doc.published_version = version.name
    doc.save(ignore_permissions=True)
    return get_template(doc.name)


def reject_template(template: str, rejection_reason: str) -> dict[str, Any]:
    _require_system_manager("Rejecting AI Workflow Templates requires System Manager.")
    reason = str(rejection_reason or "").strip()
    if not reason:
        frappe.throw("Rejection reason is required.", frappe.ValidationError)
    doc = frappe.get_doc("AI Workflow Template", template)
    if doc.status != "IN_REVIEW":
        frappe.throw("Only IN_REVIEW templates can be rejected.", frappe.ValidationError)
    doc.status = "REJECTED"
    doc.reviewed_by = frappe.session.user
    doc.reviewed_at = now_datetime()
    doc.rejection_reason = reason
    doc.review_notes = reason
    doc.save(ignore_permissions=True)
    return get_template(doc.name)


def archive_template(template: str, reason: str | None = None) -> dict[str, Any]:
    _require_system_manager("Archiving AI Workflow Templates requires System Manager.")
    doc = frappe.get_doc("AI Workflow Template", template)
    if doc.status == "ARCHIVED":
        return get_template(doc.name)
    doc.status = "ARCHIVED"
    doc.reviewed_by = frappe.session.user
    doc.reviewed_at = now_datetime()
    if reason:
        doc.review_notes = str(reason)
    doc.save(ignore_permissions=True)
    _mark_active_template_versions(doc.name, "ARCHIVED")
    return get_template(doc.name)


def list_template_versions(template: str) -> dict[str, Any]:
    doc = frappe.get_doc("AI Workflow Template", template)
    _assert_can_view_template_versions(doc)
    rows = frappe.get_all(
        "AI Workflow Template Version",
        filters={"template": doc.name},
        fields=[
            "name",
            "template",
            "version_no",
            "status",
            "template_name",
            "category",
            "description",
            "preview_asset",
            "snapshot_hash",
            "approved_by",
            "approved_at",
            "source_template_modified",
            "owner",
            "creation",
            "modified",
        ],
        order_by="version_no desc",
    )
    return {"versions": [dict(row) for row in rows]}


def get_template_version(template_version: str) -> dict[str, Any]:
    version = frappe.get_doc("AI Workflow Template Version", template_version)
    template_doc = frappe.get_doc("AI Workflow Template", version.template)
    _assert_can_view_template_versions(template_doc)
    return _template_version_summary(version)


def rollback_template_to_version(
    *,
    template: str,
    template_version: str,
    review_notes: str | None = None,
) -> dict[str, Any]:
    _require_system_manager("Rolling back AI Workflow Templates requires System Manager.")
    doc = frappe.get_doc("AI Workflow Template", template)
    target = frappe.get_doc("AI Workflow Template Version", template_version)
    if target.template != doc.name:
        frappe.throw("Template version does not belong to the selected template.", frappe.ValidationError)
    _validate_template_version_snapshot(target)
    now = now_datetime()
    version = _create_template_version_from_version(
        target,
        approved_by=frappe.session.user,
        approved_at=now,
        previous_active_status="ROLLED_BACK",
    )
    doc.template_name = version.template_name
    doc.category = version.category
    doc.description = version.description
    doc.preview_asset = version.preview_asset
    doc.nodes_json = version.nodes_json
    doc.edges_json = version.edges_json
    doc.layout_json = version.layout_json
    doc.input_schema_json = version.input_schema_json
    doc.status = "PUBLISHED"
    doc.reviewed_by = frappe.session.user
    doc.reviewed_at = now
    doc.review_notes = review_notes
    doc.rejection_reason = None
    doc.published_at = now
    doc.published_version = version.name
    doc.save(ignore_permissions=True)
    return get_template(doc.name)


def list_published_templates(category: str | None = None) -> dict[str, Any]:
    filters: dict[str, Any] = {"status": "PUBLISHED"}
    if category:
        filters["category"] = category
    templates = frappe.get_all(
        "AI Workflow Template",
        filters=filters,
        fields=["name", "modified"],
        order_by="modified desc",
    )
    rows = []
    for template in templates:
        version = _get_active_template_version(template.name)
        if version:
            rows.append(_public_template_summary(version, template.modified))
    return {"templates": rows}


def get_published_template(template: str) -> dict[str, Any]:
    doc = frappe.get_doc("AI Workflow Template", template)
    if doc.status != "PUBLISHED":
        frappe.throw(f"Template is not published: {template}", frappe.PermissionError)
    version = _get_active_template_version(doc.name, getattr(doc, "published_version", None))
    if not version:
        frappe.throw(f"Template has no active published version: {template}", frappe.PermissionError)
    return _public_template_payload(version, doc.modified)


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


def _assert_can_edit_template(doc) -> None:
    if doc.status not in OWNER_EDITABLE_STATUSES and doc.status != "PUBLISHED":
        frappe.throw("Only DRAFT or REJECTED templates can be edited through save_template.", frappe.PermissionError)
    if _is_system_manager():
        return
    if doc.owner != frappe.session.user:
        frappe.throw("You can only edit your own templates.", frappe.PermissionError)


def _assert_save_status_allowed(status: str, doc) -> None:
    if status in REVIEW_CONTROLLED_STATUSES:
        frappe.throw(
            f"Template status {status} can only be set through the dedicated review APIs.",
            frappe.ValidationError,
        )
    if status == "REJECTED" and (doc is None or doc.status != "REJECTED"):
        frappe.throw(
            "REJECTED status can only be preserved while editing an already rejected template.",
            frappe.ValidationError,
        )
    if doc is not None and doc.status == "REJECTED" and status != "REJECTED":
        frappe.throw(
            "Rejected templates must remain REJECTED until submitted for review.",
            frappe.ValidationError,
        )
    if doc is not None and doc.status == "PUBLISHED" and status != "DRAFT":
        frappe.throw(
            "Published template draft content can only be edited through a DRAFT save before review.",
            frappe.ValidationError,
        )


def _assert_can_submit_template(doc) -> None:
    if _is_system_manager():
        return
    if frappe.session.user == "Guest":
        frappe.throw("Login is required to submit templates for review.", frappe.PermissionError)
    if doc.owner != frappe.session.user:
        frappe.throw("You can only submit your own templates for review.", frappe.PermissionError)


def _require_system_manager(message: str) -> None:
    if not _is_system_manager():
        frappe.throw(message, frappe.PermissionError)


def _is_system_manager() -> bool:
    if frappe.session.user == "Administrator":
        return True
    return "System Manager" in frappe.get_roles(frappe.session.user)


def _validate_template_for_publication(doc) -> None:
    nodes = _loads_json(doc.nodes_json, [])
    edges = _loads_json(doc.edges_json, [])
    validate_workflow({"nodes": nodes, "edges": edges})
    normalize_input_schema(_loads_json(getattr(doc, "input_schema_json", None), []), nodes)
    _validate_required_public_metadata(doc)
    _validate_preview_asset(doc)
    _validate_safe_template_payload(nodes, edges, _loads_json(getattr(doc, "input_schema_json", None), []))
    _validate_provider_nodes(nodes)


def _validate_required_public_metadata(doc) -> None:
    if not str(doc.category or "").strip():
        frappe.throw("Template category is required before publishing.", frappe.ValidationError)
    if not str(doc.description or "").strip():
        frappe.throw("Template description is required before publishing.", frappe.ValidationError)


def _validate_preview_asset(doc) -> None:
    if doc.preview_asset and not frappe.db.exists("AI Asset", doc.preview_asset):
        frappe.throw(f"Preview asset does not exist: {doc.preview_asset}.", frappe.ValidationError)


def _validate_safe_template_payload(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], input_schema: Any) -> None:
    payload = json.dumps({"nodes": nodes, "edges": edges, "input_schema": input_schema}, default=str)
    for fragment in FORBIDDEN_TEMPLATE_FRAGMENTS:
        if fragment in payload:
            frappe.throw(f"Template payload contains forbidden provider/internal data: {fragment}.", frappe.ValidationError)
    for node in nodes:
        config = node.get("config") or {}
        for key in config:
            if str(key).lower() in FORBIDDEN_NODE_CONFIG_KEYS:
                frappe.throw(f"Template node config exposes forbidden field: {key}.", frappe.ValidationError)


def _validate_provider_nodes(nodes: list[dict[str, Any]]) -> None:
    for node in nodes:
        node_type = str(node.get("type") or "")
        if not node_type.startswith("provider_"):
            continue
        config = node.get("config") or {}
        provider = str(config.get("provider") or "").strip()
        model_ref = str(config.get("model") or "").strip()
        if not provider:
            frappe.throw(f"Provider node {node.get('id') or node_type} is missing provider.", frappe.ValidationError)
        if not model_ref:
            frappe.throw(f"Provider node {node.get('id') or node_type} is missing model.", frappe.ValidationError)
        model = _resolve_model(model_ref)
        if model.status != "ENABLED":
            frappe.throw(f"Provider node {node.get('id') or node_type} uses disabled model {model_ref}.", frappe.ValidationError)
        if model.provider != provider:
            frappe.throw(
                f"Provider node {node.get('id') or node_type} model/provider mismatch: {model_ref}.",
                frappe.ValidationError,
            )
        if node_type and model.node_type and model.node_type != node_type:
            frappe.throw(
                f"Provider node {node.get('id') or node_type} model node_type mismatch: {model_ref}.",
                frappe.ValidationError,
            )


def _resolve_model(model_ref: str):
    if frappe.db.exists("AI Model", model_ref):
        return frappe.get_doc("AI Model", model_ref)
    matches = frappe.get_all(
        "AI Model",
        filters={"model_id": model_ref},
        fields=["name"],
        order_by="creation asc",
        limit=1,
    )
    if not matches:
        matches = frappe.get_all(
            "AI Model",
            filters={"model_slug": model_ref},
            fields=["name"],
            order_by="creation asc",
            limit=1,
        )
    if not matches:
        frappe.throw(f"Provider model is not configured: {model_ref}.", frappe.ValidationError)
    return frappe.get_doc("AI Model", matches[0].name)


def _create_template_version(doc, *, approved_by: str, approved_at, previous_active_status: str):
    _mark_active_template_versions(doc.name, previous_active_status)
    version_no = _next_template_version_no(doc.name)
    snapshot = _template_snapshot_from_doc(doc)
    return frappe.get_doc(
        {
            "doctype": "AI Workflow Template Version",
            "template": doc.name,
            "version_no": version_no,
            "status": "ACTIVE",
            "template_name": doc.template_name,
            "category": doc.category,
            "description": doc.description,
            "preview_asset": doc.preview_asset,
            "nodes_json": canonical_json(snapshot["nodes"]),
            "edges_json": canonical_json(snapshot["edges"]),
            "layout_json": canonical_json(snapshot["layout"]),
            "input_schema_json": canonical_json(snapshot["input_schema"]),
            "snapshot_hash": snapshot_hash(snapshot),
            "approved_by": approved_by,
            "approved_at": approved_at,
            "source_template_modified": doc.modified,
            "owner": doc.owner,
        }
    ).insert(ignore_permissions=True)


def _create_template_version_from_version(version, *, approved_by: str, approved_at, previous_active_status: str):
    _mark_active_template_versions(version.template, previous_active_status)
    snapshot = _template_snapshot_from_version(version)
    return frappe.get_doc(
        {
            "doctype": "AI Workflow Template Version",
            "template": version.template,
            "version_no": _next_template_version_no(version.template),
            "status": "ACTIVE",
            "template_name": version.template_name,
            "category": version.category,
            "description": version.description,
            "preview_asset": version.preview_asset,
            "nodes_json": canonical_json(snapshot["nodes"]),
            "edges_json": canonical_json(snapshot["edges"]),
            "layout_json": canonical_json(snapshot["layout"]),
            "input_schema_json": canonical_json(snapshot["input_schema"]),
            "snapshot_hash": snapshot_hash(snapshot),
            "approved_by": approved_by,
            "approved_at": approved_at,
            "source_template_modified": version.source_template_modified,
            "owner": version.owner,
        }
    ).insert(ignore_permissions=True)


def _template_snapshot_from_doc(doc) -> dict[str, Any]:
    nodes = _loads_json(doc.nodes_json, [])
    edges = _loads_json(doc.edges_json, [])
    layout = _loads_json(doc.layout_json, {})
    input_schema = _loads_json(getattr(doc, "input_schema_json", None), [])
    return _template_snapshot(
        template_name=doc.template_name,
        category=doc.category,
        description=doc.description,
        preview_asset=doc.preview_asset,
        nodes=nodes,
        edges=edges,
        layout=layout,
        input_schema=input_schema,
    )


def _template_snapshot_from_version(version) -> dict[str, Any]:
    return _template_snapshot(
        template_name=version.template_name,
        category=version.category,
        description=version.description,
        preview_asset=version.preview_asset,
        nodes=_loads_json(version.nodes_json, []),
        edges=_loads_json(version.edges_json, []),
        layout=_loads_json(version.layout_json, {}),
        input_schema=_loads_json(version.input_schema_json, []),
    )


def _template_snapshot(
    *,
    template_name: str,
    category: str | None,
    description: str | None,
    preview_asset: str | None,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    layout: Any,
    input_schema: Any,
) -> dict[str, Any]:
    return {
        "template_name": template_name,
        "category": category,
        "description": description,
        "preview_asset": preview_asset,
        "nodes": nodes,
        "edges": edges,
        "layout": layout,
        "input_schema": input_schema,
    }


def _next_template_version_no(template: str) -> int:
    latest = frappe.get_all(
        "AI Workflow Template Version",
        filters={"template": template},
        fields=["version_no"],
        order_by="version_no desc",
        limit=1,
    )
    return int(latest[0].version_no) + 1 if latest else 1


def _mark_active_template_versions(template: str, status: str) -> None:
    if status not in TEMPLATE_VERSION_STATUSES:
        frappe.throw(f"Unsupported AI Workflow Template Version status: {status}", frappe.ValidationError)
    rows = frappe.get_all(
        "AI Workflow Template Version",
        filters={"template": template, "status": "ACTIVE"},
        fields=["name"],
    )
    for row in rows:
        version = frappe.get_doc("AI Workflow Template Version", row.name)
        version.status = status
        version.save(ignore_permissions=True)


def _get_active_template_version(template: str, preferred_version: str | None = None):
    if preferred_version and frappe.db.exists("AI Workflow Template Version", preferred_version):
        version = frappe.get_doc("AI Workflow Template Version", preferred_version)
        if version.template == template and version.status == "ACTIVE":
            return version
    rows = frappe.get_all(
        "AI Workflow Template Version",
        filters={"template": template, "status": "ACTIVE"},
        fields=["name"],
        order_by="version_no desc",
        limit=1,
    )
    return frappe.get_doc("AI Workflow Template Version", rows[0].name) if rows else None


def _public_template_summary(version, template_modified=None) -> dict[str, Any]:
    return {
        "name": version.template,
        "template": version.template,
        "template_version": version.name,
        "version_no": version.version_no,
        "snapshot_hash": version.snapshot_hash,
        "template_name": version.template_name,
        "status": "PUBLISHED",
        "category": version.category,
        "description": version.description,
        "preview_asset": version.preview_asset,
        "published_at": version.approved_at,
        "modified": template_modified or version.modified,
    }


def _public_template_payload(version, template_modified=None) -> dict[str, Any]:
    return _public_template_summary(version, template_modified) | {
        "nodes": _loads_json(version.nodes_json, []),
        "edges": _loads_json(version.edges_json, []),
        "layout": _loads_json(version.layout_json, {}),
        "input_schema": _loads_json(version.input_schema_json, []),
    }


def _template_version_summary(version) -> dict[str, Any]:
    return {
        "name": version.name,
        "template": version.template,
        "version_no": version.version_no,
        "status": version.status,
        "template_name": version.template_name,
        "category": version.category,
        "description": version.description,
        "preview_asset": version.preview_asset,
        "snapshot_hash": version.snapshot_hash,
        "approved_by": version.approved_by,
        "approved_at": version.approved_at,
        "source_template_modified": version.source_template_modified,
        "owner": version.owner,
        "created": version.creation,
        "modified": version.modified,
    }


def _validate_template_version_snapshot(version) -> None:
    nodes = _loads_json(version.nodes_json, [])
    edges = _loads_json(version.edges_json, [])
    input_schema = _loads_json(version.input_schema_json, [])
    validate_workflow({"nodes": nodes, "edges": edges})
    normalize_input_schema(input_schema, nodes)
    _validate_required_public_metadata(version)
    _validate_preview_asset(version)
    _validate_safe_template_payload(nodes, edges, input_schema)
    _validate_provider_nodes(nodes)
    snapshot = _template_snapshot_from_version(version)
    if snapshot_hash(snapshot) != version.snapshot_hash:
        frappe.throw("Template version snapshot hash does not match persisted payload.", frappe.ValidationError)


def _assert_can_view_template_versions(doc) -> None:
    if _is_system_manager():
        return
    if frappe.session.user == "Guest":
        frappe.throw("Login is required to view template versions.", frappe.PermissionError)
    if doc.owner != frappe.session.user:
        frappe.throw("You can only view versions for your own templates.", frappe.PermissionError)

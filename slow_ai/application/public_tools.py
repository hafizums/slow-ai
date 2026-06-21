"""Published template access for user-facing tool runs."""

from __future__ import annotations

import json
import secrets
from datetime import timedelta
from decimal import Decimal
from typing import Any

import frappe
from frappe.utils import get_datetime
from frappe.utils import now_datetime

from slow_ai.application.assets import view as view_asset
from slow_ai.application.project_access import (
    assert_can_edit_project,
    assert_can_share_run,
    assert_can_view_project,
    can_edit_project,
    can_manage_project_members,
    is_system_manager,
    list_accessible_project_names,
)
from slow_ai.application.templates import get_published_template
from slow_ai.application.templates import get_template_version_payload
from slow_ai.application.templates import list_published_templates
from slow_ai.application.run_outputs import get_run_output_gallery as get_run_output_gallery_service
from slow_ai.application.safe_payloads import asset_names_from_value
from slow_ai.application.safe_payloads import redact_text
from slow_ai.application.safe_payloads import safe_node_output_summary
from slow_ai.application.template_lineage import safe_template_lineage
from slow_ai.application.template_inputs import apply_input_values
from slow_ai.application.template_inputs import apply_legacy_public_tool_values
from slow_ai.application.template_inputs import extract_input_values_from_nodes
from slow_ai.application.workflows import save_workflow
from slow_ai.domain.status import (
    NODE_TERMINAL_STATUSES,
    PROVIDER_JOB_TERMINAL_STATUSES,
    WORKFLOW_TERMINAL_STATUSES,
    NodeRunStatus,
    ProviderJobStatus,
    WorkflowRunStatus,
)
from slow_ai.engine.state_machine import transition_node_run
from slow_ai.engine.state_machine import transition_workflow_run
from slow_ai.infrastructure.provider_jobs import ProviderJobRepository
from slow_ai.infrastructure.repositories import FrappeEngineRepository


CANCELLABLE_WORKFLOW_STATUSES = frozenset(
    {
        WorkflowRunStatus.QUEUED,
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.WAITING_PROVIDER,
    }
)
CANCELLATION_ERROR = {"type": "RunCancelled", "message": "Run cancelled by user."}
DEFAULT_TOOL_DRAFT_CLEANUP_AGE_HOURS = 24


def list_templates(category: str | None = None) -> dict[str, Any]:
    _require_logged_in_user()
    return list_published_templates(category=category)


def get_template(template: str) -> dict[str, Any]:
    _require_logged_in_user()
    return get_published_template(template)


def create_workflow_from_template(
    *,
    template: str,
    project: str,
    title: str | None = None,
) -> dict[str, Any]:
    _require_logged_in_user()
    payload = get_published_template(template)
    assert_can_edit_project(project)
    return save_workflow(
        project=project,
        title=title or payload["template_name"],
        nodes=payload["nodes"],
        edges=payload["edges"],
        layout=payload["layout"],
        status="DRAFT",
        source_template=payload["template"],
        source_template_version=payload["template_version"],
    )


def prepare_workflow_from_template(
    *,
    template: str,
    project: str,
    title: str | None = None,
    values: Any | None = None,
) -> dict[str, Any]:
    _require_logged_in_user()
    payload = get_published_template(template)
    assert_can_edit_project(project)
    input_schema = payload.get("input_schema") or []
    if input_schema:
        nodes = apply_input_values(
            nodes=payload["nodes"],
            input_schema=input_schema,
            values=values,
            project=project,
        )
    else:
        nodes = apply_legacy_public_tool_values(nodes=payload["nodes"], values=values, project=project)
    return save_workflow(
        project=project,
        title=title or payload["template_name"],
        nodes=nodes,
        edges=payload["edges"],
        layout=payload["layout"],
        status="DRAFT",
        source_template=payload["template"],
        source_template_version=payload["template_version"],
        is_temporary_tool_draft=True,
        tool_draft_type="PREPARED",
    )


def prepare_rerun_from_run(
    *,
    workflow_run: str,
    title: str | None = None,
) -> dict[str, Any]:
    _require_logged_in_user()
    run = frappe.get_doc("AI Workflow Run", workflow_run)
    assert_can_view_project(run.project)
    assert_can_edit_project(run.project)
    source_template = str(getattr(run, "source_template", None) or "").strip()
    source_template_version = str(getattr(run, "source_template_version", None) or "").strip()
    if not source_template or not source_template_version:
        frappe.throw("This run has no template version lineage for rerun.", frappe.ValidationError)

    payload = get_template_version_payload(source_template, source_template_version)
    previous_workflow = frappe.get_doc("AI Workflow", run.workflow)
    previous_nodes = _loads_json(previous_workflow.draft_nodes_json, [])
    input_schema = payload.get("input_schema") or []
    prefilled_values = extract_input_values_from_nodes(nodes=previous_nodes, input_schema=input_schema)
    nodes = (
        apply_input_values(
            nodes=payload["nodes"],
            input_schema=input_schema,
            values=prefilled_values,
            project=run.project,
        )
        if input_schema
        else payload["nodes"]
    )
    draft = save_workflow(
        project=run.project,
        title=title or f"Rerun of {frappe.db.get_value('AI Workflow', run.workflow, 'title') or payload['template_name']}",
        nodes=nodes,
        edges=payload["edges"],
        layout=payload["layout"],
        status="DRAFT",
        source_template=payload["template"],
        source_template_version=payload["template_version"],
        is_temporary_tool_draft=True,
        tool_draft_type="RERUN",
    )
    return {
        "workflow": draft,
        "template": payload,
        "prefilled_values": prefilled_values,
        "source_run": _run_summary(run.as_dict()),
    }


def update_rerun_draft_values(
    *,
    workflow: str,
    values: Any | None = None,
) -> dict[str, Any]:
    _require_logged_in_user()
    doc = frappe.get_doc("AI Workflow", workflow)
    assert_can_edit_project(doc.project)
    if frappe.db.exists("AI Workflow Run", {"workflow": doc.name}):
        frappe.throw("Rerun draft values cannot be updated after a run has started.", frappe.ValidationError)

    source_template = str(getattr(doc, "source_template", None) or "").strip()
    source_template_version = str(getattr(doc, "source_template_version", None) or "").strip()
    if not source_template or not source_template_version:
        frappe.throw("This workflow has no template version lineage for rerun.", frappe.ValidationError)

    payload = get_template_version_payload(source_template, source_template_version)
    input_schema = payload.get("input_schema") or []
    submitted = _loads_json(values, {})
    if not input_schema:
        nodes = apply_legacy_public_tool_values(
            nodes=_loads_json(doc.draft_nodes_json, []),
            values=submitted,
            project=doc.project,
        )
    else:
        nodes = apply_input_values(
            nodes=_loads_json(doc.draft_nodes_json, []),
            input_schema=input_schema,
            values=submitted,
            project=doc.project,
        )

    return save_workflow(
        workflow=doc.name,
        project=doc.project,
        title=doc.title,
        nodes=nodes,
        edges=_loads_json(doc.draft_edges_json, []),
        layout=_loads_json(doc.layout_json, {}),
        status=doc.status,
        source_template=payload["template"],
        source_template_version=payload["template_version"],
    )


def cleanup_stale_tool_drafts(
    *,
    max_age_hours: int | str | None = DEFAULT_TOOL_DRAFT_CLEANUP_AGE_HOURS,
    limit: int | str = 100,
    dry_run: bool | str | int = False,
) -> dict[str, Any]:
    _require_logged_in_user()
    _require_system_manager()
    hours = _as_positive_hours(max_age_hours)
    cutoff = now_datetime() - timedelta(hours=hours)
    delete_enabled = not _as_bool(dry_run)
    rows = frappe.get_all(
        "AI Workflow",
        filters={
            "status": "DRAFT",
            "is_temporary_tool_draft": 1,
        },
        fields=[
            "name",
            "source_template",
            "source_template_version",
            "tool_draft_type",
            "tool_draft_prepared_at",
            "modified",
        ],
        order_by="modified asc",
        limit=_as_limit(limit),
    )
    deleted: list[str] = []
    skipped: list[dict[str, str]] = []
    for row in rows:
        workflow = row.get("name")
        if not workflow:
            continue
        if not row.get("source_template") or not row.get("source_template_version"):
            skipped.append({"workflow": workflow, "reason": "missing_template_lineage"})
            continue
        prepared_at = get_datetime(row.get("tool_draft_prepared_at") or row.get("modified"))
        if prepared_at > cutoff:
            skipped.append({"workflow": workflow, "reason": "fresh"})
            continue
        if frappe.db.exists("AI Workflow Run", {"workflow": workflow}):
            skipped.append({"workflow": workflow, "reason": "has_run"})
            continue
        if frappe.db.exists("AI Workflow Version", {"workflow": workflow}):
            skipped.append({"workflow": workflow, "reason": "has_workflow_version"})
            continue
        deleted.append(workflow)
        if delete_enabled:
            frappe.delete_doc(
                "AI Workflow",
                workflow,
                ignore_permissions=True,
                ignore_missing=True,
                delete_permanently=True,
            )
    return {
        "deleted_count": len(deleted),
        "deleted_workflows": deleted,
        "skipped": skipped,
        "dry_run": not delete_enabled,
        "max_age_hours": hours,
        "cutoff": cutoff,
    }


def list_my_runs(
    project: str | None = None,
    limit: int | str = 50,
    include_archived: bool | str | int = False,
) -> dict[str, Any]:
    _require_logged_in_user()
    filters = _run_filters(project)
    if filters is None:
        return {"runs": []}
    if not _as_bool(include_archived):
        filters["is_archived"] = 0

    rows = frappe.get_all(
        "AI Workflow Run",
        filters=filters,
        fields=[
            "name",
            "workflow",
            "project",
            "source_template",
            "source_template_version",
            "status",
            "queued_at",
            "started_at",
            "completed_at",
            "is_archived",
            "archived_by",
            "archived_at",
            "creation",
            "modified",
        ],
        order_by="creation desc",
        limit=_as_limit(limit),
    )
    return {"runs": [_run_summary(row) for row in rows]}


def get_my_run(workflow_run: str) -> dict[str, Any]:
    _require_logged_in_user()
    run = frappe.get_doc("AI Workflow Run", workflow_run)
    assert_can_view_project(run.project)

    node_runs = frappe.get_all(
        "AI Node Run",
        filters={"workflow_run": run.name},
        fields=[
            "name",
            "node_id",
            "node_type",
            "status",
            "provider_job",
            "cost_usd",
            "output_json",
            "error_json",
            "started_at",
            "completed_at",
        ],
        order_by="creation asc",
    )
    provider_jobs = _provider_job_summaries(node_runs)
    assets = _asset_summaries(run.name)
    ledger = _ledger_summaries(run.name)
    output_gallery = get_run_output_gallery_service(run.name)
    return {
        "run": _run_summary(run.as_dict()) | {"error": _safe_error(run.error_json)},
        "node_runs": [_node_run_summary(row) for row in node_runs],
        "provider_jobs": provider_jobs,
        "provider_summary": _status_summary(provider_jobs),
        "assets": assets,
        "output_gallery": output_gallery,
        "ledger": ledger,
        "cost_summary": _cost_summary(ledger),
    }


def get_run_output_gallery(workflow_run: str) -> dict[str, Any]:
    _require_logged_in_user()
    return get_run_output_gallery_service(workflow_run)


def cancel_my_run(workflow_run: str) -> dict[str, Any]:
    _require_logged_in_user()
    run = frappe.get_doc("AI Workflow Run", workflow_run)
    assert_can_edit_project(run.project)

    current = WorkflowRunStatus(run.status)
    if current in WORKFLOW_TERMINAL_STATUSES:
        frappe.throw("Terminal tool runs cannot be cancelled.", frappe.ValidationError)
    if current not in CANCELLABLE_WORKFLOW_STATUSES:
        frappe.throw(f"Tool run cannot be cancelled from status {current.value}.", frappe.ValidationError)

    repository = FrappeEngineRepository()
    provider_jobs = ProviderJobRepository()
    node_rows = frappe.get_all(
        "AI Node Run",
        filters={"workflow_run": run.name},
        fields=["name", "status"],
        order_by="creation asc",
    )
    node_names = [row.name for row in node_rows]
    provider_rows = (
        frappe.get_all(
            "AI Provider Job",
            filters={"node_run": ["in", node_names]},
            fields=["name", "status"],
            order_by="creation asc",
        )
        if node_names
        else []
    )

    for row in provider_rows:
        status = ProviderJobStatus(row.status)
        if status in PROVIDER_JOB_TERMINAL_STATUSES:
            continue
        provider_jobs.mark_cancelled(row.name)

    for row in node_rows:
        status = NodeRunStatus(row.status)
        if status in NODE_TERMINAL_STATUSES:
            continue
        transition_node_run(status, NodeRunStatus.CANCELLED)
        repository.set_node_status(row.name, NodeRunStatus.CANCELLED, error=CANCELLATION_ERROR)

    transition_workflow_run(current, WorkflowRunStatus.CANCELLED)
    repository.set_workflow_status(run.name, WorkflowRunStatus.CANCELLED, CANCELLATION_ERROR)
    run.reload()
    return {"run": _run_summary(run.as_dict()) | {"error": _safe_error(run.error_json)}}


def archive_my_run(workflow_run: str) -> dict[str, Any]:
    _require_logged_in_user()
    run = frappe.get_doc("AI Workflow Run", workflow_run)
    assert_can_edit_project(run.project)

    current = WorkflowRunStatus(run.status)
    if current not in WORKFLOW_TERMINAL_STATUSES:
        frappe.throw("Only terminal tool runs can be archived.", frappe.ValidationError)

    if not run.get("is_archived"):
        run.is_archived = 1
        run.archived_by = frappe.session.user
        run.archived_at = now_datetime()
        run.save(ignore_permissions=True)
    return {"run": _run_summary(run.as_dict()) | {"error": _safe_error(run.error_json)}}


def create_run_share(
    workflow_run: str,
    selected_assets: Any | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    _require_logged_in_user()
    run = frappe.get_doc("AI Workflow Run", workflow_run)
    assert_can_share_run(run.project)
    _assert_shareable_run(run)
    selected_asset_names = _validate_selected_assets(run.name, selected_assets)

    existing = _get_existing_share_for_user(run.name, selected_asset_names)
    if existing:
        return {"share": _share_summary(existing)}

    share = frappe.get_doc(
        {
            "doctype": "AI Tool Run Share",
            "workflow_run": run.name,
            "project": run.project,
            "share_token": _new_share_token(),
            "status": "ACTIVE",
            "selected_assets_json": json.dumps(selected_asset_names),
            "expires_at": expires_at,
        }
    ).insert(ignore_permissions=True)
    return {"share": _share_summary(share.as_dict())}


def disable_run_share(share_token: str | None = None, share: str | None = None) -> dict[str, Any]:
    _require_logged_in_user()
    doc = _get_share_doc(share_token=share_token, share=share)
    _assert_share_manage_access(doc)
    doc.status = "DISABLED"
    doc.save(ignore_permissions=True)
    return {"share": _share_summary(doc.as_dict())}


def get_shared_run(share_token: str) -> dict[str, Any]:
    doc = _get_share_doc(share_token=share_token)
    _assert_share_readable(doc)
    run = frappe.get_doc("AI Workflow Run", doc.workflow_run)
    _assert_shareable_run(run)
    ledger = _ledger_summaries(run.name)
    selected_assets = _selected_assets_for_share(doc)
    output_gallery = get_run_output_gallery_service(
        run.name,
        selected_assets=selected_assets,
        include_unselected=False,
        ignore_project_permissions=True,
    )
    output_gallery = _public_output_gallery(output_gallery)
    return {
        "share": _public_share_summary(doc.as_dict()),
        "run": _public_run_summary(run.as_dict()),
        "assets": output_gallery["assets"],
        "output_gallery": output_gallery,
        "cost_summary": _cost_summary(ledger),
    }


def _require_logged_in_user() -> None:
    if frappe.session.user == "Guest":
        frappe.throw("Login is required to run Slow AI tools.", frappe.PermissionError)


def _require_system_manager() -> None:
    if not is_system_manager():
        frappe.throw("System Manager is required to clean public tool drafts.", frappe.PermissionError)


def _assert_template_published(template: dict[str, Any]) -> None:
    if template.get("status") != "PUBLISHED":
        frappe.throw(
            f"Template is not published: {template.get('name') or ''}",
            frappe.PermissionError,
        )


def _assert_project_access(project: str) -> None:
    assert_can_view_project(project)


def _run_filters(project: str | None) -> dict[str, Any] | None:
    project_name = str(project or "").strip()
    if project_name:
        assert_can_view_project(project_name)
        return {"project": project_name}
    if is_system_manager():
        return {}
    projects = list_accessible_project_names("view")
    if not projects:
        return None
    return {"project": ["in", projects]}


def _run_summary(row) -> dict[str, Any]:
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
        "is_archived": 1 if row.get("is_archived") else 0,
        "archived_by": row.get("archived_by"),
        "archived_at": row.get("archived_at"),
        "provider_summary": _provider_summary_for_run(row.get("name")),
        "cost_summary": _cost_summary(_ledger_summaries(row.get("name"))),
        "asset_count": frappe.db.count("AI Asset", {"source_workflow_run": row.get("name")}) if row.get("name") else 0,
        "share": _share_summary_for_run(row.get("name")),
        "can_cancel": _can_cancel_run(row),
        "can_archive": _can_archive_run(row),
        "template_lineage": safe_template_lineage(
            row.get("source_template"),
            row.get("source_template_version"),
        ),
    }


def _public_run_summary(row) -> dict[str, Any]:
    workflow = row.get("workflow")
    return {
        "workflow_run": row.get("name"),
        "workflow_title": frappe.db.get_value("AI Workflow", workflow, "title") if workflow else None,
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


def _can_cancel_run(row) -> bool:
    try:
        status = WorkflowRunStatus(row.get("status"))
    except ValueError:
        return False
    project = row.get("project")
    if not project or status not in CANCELLABLE_WORKFLOW_STATUSES:
        return False
    try:
        return can_edit_project(project)
    except frappe.PermissionError:
        return False


def _can_archive_run(row) -> bool:
    try:
        status = WorkflowRunStatus(row.get("status"))
    except ValueError:
        return False
    project = row.get("project")
    if not project or status not in WORKFLOW_TERMINAL_STATUSES or row.get("is_archived"):
        return False
    try:
        return can_edit_project(project)
    except frappe.PermissionError:
        return False


def _public_output_gallery(gallery: dict[str, Any]) -> dict[str, Any]:
    run = gallery.get("run") or {}
    public_assets = [_public_gallery_asset(asset) for asset in gallery.get("assets", [])]
    public_groups = []
    for group in gallery.get("groups", []):
        public_group = dict(group)
        public_group["assets"] = [_public_gallery_asset(asset) for asset in group.get("assets", [])]
        public_groups.append(public_group)
    return {
        **gallery,
        "run": {
            "workflow_run": run.get("workflow_run"),
            "workflow_title": run.get("workflow_title"),
            "status": run.get("status"),
            "queued_at": run.get("queued_at"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "created": run.get("created"),
            "modified": run.get("modified"),
            "template_lineage": run.get("template_lineage"),
        },
        "groups": public_groups,
        "assets": public_assets,
    }


def _public_gallery_asset(asset: dict[str, Any]) -> dict[str, Any]:
    safe = _safe_shared_asset(asset)
    safe["source_output"] = asset.get("source_output")
    safe["selected"] = 1 if asset.get("selected") else 0
    safe["shareable"] = 1 if asset.get("shareable") else 0
    return safe


def _provider_summary_for_run(workflow_run: str | None) -> dict[str, Any]:
    if not workflow_run:
        return {}
    node_names = frappe.get_all("AI Node Run", filters={"workflow_run": workflow_run}, pluck="name")
    if not node_names:
        return {}
    rows = frappe.get_all(
        "AI Provider Job",
        filters={"node_run": ["in", node_names]},
        fields=["status"],
    )
    return _status_summary(rows)


def _provider_job_summaries(node_runs) -> list[dict[str, Any]]:
    node_names = [row.name for row in node_runs]
    if not node_names:
        return []
    rows = frappe.get_all(
        "AI Provider Job",
        filters={"node_run": ["in", node_names]},
        fields=[
            "name",
            "node_run",
            "provider",
            "model",
            "status",
            "cost_usd",
            "estimated_cost_usd",
            "debit_cost_usd",
            "debit_cost_source",
            "submitted_at",
            "completed_at",
        ],
        order_by="creation asc",
    )
    return [
        {
            "name": row.name,
            "node_run": row.node_run,
            "provider": row.provider,
            "model": row.model,
            "status": row.status,
            "cost_usd": _decimal_string(row.cost_usd),
            "estimated_cost_usd": _decimal_string(row.estimated_cost_usd),
            "debit_cost_usd": _decimal_string(row.debit_cost_usd),
            "debit_cost_source": row.debit_cost_source,
            "submitted_at": row.submitted_at,
            "completed_at": row.completed_at,
        }
        for row in rows
    ]


def _node_run_summary(row) -> dict[str, Any]:
    output = _loads_json(row.output_json, {})
    return {
        "name": row.name,
        "node_id": row.node_id,
        "node_type": row.node_type,
        "status": row.status,
        "provider_job": row.provider_job,
        "cost_usd": _decimal_string(row.cost_usd),
        "output": safe_node_output_summary(output),
        "asset_names": asset_names_from_value(output),
        "error": _safe_error(row.error_json),
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


def _asset_summaries(workflow_run: str) -> list[dict[str, Any]]:
    rows = frappe.get_all(
        "AI Asset",
        filters={"source_workflow_run": workflow_run},
        fields=[
            "name",
            "asset_type",
            "mime_type",
            "source_workflow_run",
            "source_node_run",
            "source_provider_job",
            "creation",
            "modified",
        ],
        order_by="creation asc",
    )
    return [dict(row) for row in rows]


def _shared_asset_views(names: list[str]) -> list[dict[str, Any]]:
    assets = []
    for asset_name in names:
        if frappe.db.exists("AI Asset", asset_name):
            assets.append(_safe_shared_asset(view_asset(asset_name, ignore_project_permissions=True)))
    return assets


def _asset_names_for_run(workflow_run: str) -> list[str]:
    names = {row["name"] for row in _asset_summaries(workflow_run)}
    node_runs = frappe.get_all(
        "AI Node Run",
        filters={"workflow_run": workflow_run},
        fields=["output_json"],
        order_by="creation asc",
    )
    for row in node_runs:
        names.update(asset_names_from_value(_loads_json(row.output_json, {})))
    return sorted(names)


def _validate_selected_assets(workflow_run: str, selected_assets: Any | None) -> list[str]:
    selected = _normalize_selected_assets(selected_assets)
    if not selected:
        frappe.throw("Select at least one output asset to share.", frappe.ValidationError)

    run_assets = set(_asset_names_for_run(workflow_run))
    for asset_name in selected:
        if not frappe.db.exists("AI Asset", asset_name):
            frappe.throw(f"Selected asset does not exist: {asset_name}.", frappe.ValidationError)
        if asset_name not in run_assets:
            frappe.throw(f"Selected asset does not belong to this workflow run: {asset_name}.", frappe.PermissionError)
    return selected


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


def _selected_assets_for_share(share_doc) -> list[str]:
    return _normalize_selected_assets(share_doc.selected_assets_json)


def _safe_shared_asset(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": asset.get("name"),
        "asset_type": asset.get("asset_type"),
        "file": asset.get("file"),
        "url": asset.get("url"),
        "mime_type": asset.get("mime_type"),
        "width": asset.get("width"),
        "height": asset.get("height"),
        "duration_seconds": asset.get("duration_seconds"),
        "source_workflow_run": asset.get("source_workflow_run"),
        "source_node_run": asset.get("source_node_run"),
        "created": asset.get("created"),
        "modified": asset.get("modified"),
        "metadata": asset.get("metadata") or {},
    }


def _ledger_summaries(workflow_run: str | None) -> list[dict[str, Any]]:
    if not workflow_run:
        return []
    rows = frappe.get_all(
        "AI Credit Ledger",
        filters={"workflow_run": workflow_run},
        fields=["name", "node_run", "provider_job", "ledger_type", "amount_usd", "currency"],
        order_by="creation asc",
    )
    return [
        {
            **dict(row),
            "amount_usd": _decimal_string(row.amount_usd),
        }
        for row in rows
    ]


def _cost_summary(ledger_rows: list[dict[str, Any]]) -> dict[str, Any]:
    debits = Decimal("0")
    credits = Decimal("0")
    adjustments = Decimal("0")
    reserves = Decimal("0")
    releases = Decimal("0")
    for row in ledger_rows:
        amount = _as_decimal(row.get("amount_usd"))
        if row.get("ledger_type") == "DEBIT":
            debits += amount
        elif row.get("ledger_type") == "CREDIT":
            credits += amount
        elif row.get("ledger_type") == "ADJUSTMENT":
            adjustments += amount
        elif row.get("ledger_type") == "RESERVE":
            reserves += amount
        elif row.get("ledger_type") == "RELEASE":
            releases += amount
    return {
        "currency": "USD",
        "debits_usd": str(debits),
        "credits_usd": str(credits),
        "adjustments_usd": str(adjustments),
        "reserved_usd": str(reserves),
        "released_usd": str(releases),
        "net_usd": str(credits + adjustments + releases - debits - reserves),
    }


def _status_summary(rows) -> dict[str, Any]:
    summary: dict[str, Any] = {"total": len(rows)}
    for row in rows:
        status = row.get("status")
        if status:
            summary[status] = summary.get(status, 0) + 1
    return summary


def _safe_error(value: Any) -> str | None:
    payload = _loads_json(value, value)
    if not payload:
        return None
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error") or payload.get("status") or "Run failed."
    else:
        message = payload
    return redact_text(message)


def _loads_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default
    return value


def _as_limit(value: int | str) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 50
    return max(1, min(limit, 100))


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_positive_hours(value: int | str | None) -> int:
    try:
        hours = int(value or DEFAULT_TOOL_DRAFT_CLEANUP_AGE_HOURS)
    except (TypeError, ValueError):
        frappe.throw("Cleanup age threshold must be a positive number of hours.", frappe.ValidationError)
    if hours < 1:
        frappe.throw("Cleanup age threshold must be at least 1 hour.", frappe.ValidationError)
    return hours


def _as_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _decimal_string(value: Any) -> str:
    return str(_as_decimal(value))


def _assert_shareable_run(run) -> None:
    if run.status != "SUCCEEDED":
        frappe.throw("Only completed successful tool runs can be shared.", frappe.PermissionError)


def _assert_share_manage_access(share_doc) -> None:
    if is_system_manager():
        return
    if share_doc.owner != frappe.session.user:
        if not can_manage_project_members(share_doc.project):
            frappe.throw("You do not have access to this shared run.", frappe.PermissionError)
    assert_can_view_project(share_doc.project)


def _assert_share_readable(share_doc) -> None:
    if share_doc.status != "ACTIVE":
        frappe.throw("Shared run is not active.", frappe.PermissionError)
    if share_doc.expires_at and get_datetime(share_doc.expires_at) <= now_datetime():
        frappe.throw("Shared run has expired.", frappe.PermissionError)


def _get_share_doc(share_token: str | None = None, share: str | None = None):
    filters = {}
    if share:
        if not frappe.db.exists("AI Tool Run Share", share):
            frappe.throw("Shared run does not exist.", frappe.PermissionError)
        return frappe.get_doc("AI Tool Run Share", share)
    token = str(share_token or "").strip()
    if not token:
        frappe.throw("Share token is required.", frappe.PermissionError)
    filters["share_token"] = token
    name = frappe.db.get_value("AI Tool Run Share", filters, "name")
    if not name:
        frappe.throw("Shared run does not exist.", frappe.PermissionError)
    return frappe.get_doc("AI Tool Run Share", name)


def _get_existing_share_for_user(workflow_run: str, selected_assets: list[str]):
    rows = frappe.get_all(
        "AI Tool Run Share",
        filters={"workflow_run": workflow_run, "owner": frappe.session.user, "status": "ACTIVE"},
        fields=[
            "name",
            "workflow_run",
            "project",
            "share_token",
            "status",
            "selected_assets_json",
            "expires_at",
            "owner",
            "creation",
            "modified",
        ],
        order_by="modified desc",
    )
    for row in rows:
        if _normalize_selected_assets(row.get("selected_assets_json")) == selected_assets:
            return row
    return None


def _share_summary_for_run(workflow_run: str | None) -> dict[str, Any] | None:
    if not workflow_run:
        return None
    filters: dict[str, Any] = {"workflow_run": workflow_run}
    if not is_system_manager():
        filters["owner"] = frappe.session.user
    rows = frappe.get_all(
        "AI Tool Run Share",
        filters=filters,
        fields=[
            "name",
            "workflow_run",
            "project",
            "share_token",
            "status",
            "selected_assets_json",
            "expires_at",
            "owner",
            "creation",
            "modified",
        ],
        order_by="modified desc",
        limit=1,
    )
    if not rows:
        return None
    return _share_summary(rows[0])


def _share_summary(row) -> dict[str, Any]:
    token = row.get("share_token")
    status = row.get("status")
    return {
        "name": row.get("name"),
        "workflow_run": row.get("workflow_run"),
        "status": status,
        "expires_at": row.get("expires_at"),
        "created": row.get("creation"),
        "modified": row.get("modified"),
        "selected_assets": _normalize_selected_assets(row.get("selected_assets_json")),
        "share_token": token if status == "ACTIVE" else None,
        "share_url": f"/slow-ai/shared/{token}" if token and status == "ACTIVE" else None,
    }


def _public_share_summary(row) -> dict[str, Any]:
    return {
        "status": row.get("status"),
        "expires_at": row.get("expires_at"),
        "created": row.get("creation"),
        "modified": row.get("modified"),
    }


def _new_share_token() -> str:
    for _attempt in range(5):
        token = secrets.token_urlsafe(24)
        if not frappe.db.exists("AI Tool Run Share", {"share_token": token}):
            return token
    frappe.throw("Could not create a unique share token.")

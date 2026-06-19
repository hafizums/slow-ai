"""Published template access for user-facing tool runs."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

import frappe

from slow_ai.application.templates import create_workflow_from_template as create_template_workflow
from slow_ai.application.templates import get_template as get_template_service
from slow_ai.application.templates import list_templates as list_templates_service


def list_templates(category: str | None = None) -> dict[str, Any]:
    _require_logged_in_user()
    return list_templates_service(status="PUBLISHED", category=category)


def get_template(template: str) -> dict[str, Any]:
    _require_logged_in_user()
    payload = get_template_service(template)
    _assert_template_published(payload)
    return payload


def create_workflow_from_template(
    *,
    template: str,
    project: str,
    title: str | None = None,
) -> dict[str, Any]:
    _require_logged_in_user()
    payload = get_template_service(template)
    _assert_template_published(payload)
    _assert_project_access(project)
    return create_template_workflow(template=template, project=project, title=title)


def list_my_runs(project: str | None = None, limit: int | str = 50) -> dict[str, Any]:
    _require_logged_in_user()
    filters = _run_filters(project)
    if filters is None:
        return {"runs": []}

    rows = frappe.get_all(
        "AI Workflow Run",
        filters=filters,
        fields=[
            "name",
            "workflow",
            "project",
            "status",
            "queued_at",
            "started_at",
            "completed_at",
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
    _assert_project_access(run.project)

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
    return {
        "run": _run_summary(run.as_dict()) | {"error": _safe_error(run.error_json)},
        "node_runs": [_node_run_summary(row) for row in node_runs],
        "provider_jobs": provider_jobs,
        "provider_summary": _status_summary(provider_jobs),
        "assets": assets,
        "ledger": ledger,
        "cost_summary": _cost_summary(ledger),
    }


def _require_logged_in_user() -> None:
    if frappe.session.user == "Guest":
        frappe.throw("Login is required to run Slow AI tools.", frappe.PermissionError)


def _assert_template_published(template: dict[str, Any]) -> None:
    if template.get("status") != "PUBLISHED":
        frappe.throw(
            f"Template is not published: {template.get('name') or ''}",
            frappe.PermissionError,
        )


def _assert_project_access(project: str) -> None:
    project_name = str(project or "").strip()
    if not project_name:
        frappe.throw("AI Project is required.", frappe.PermissionError)
    if not frappe.db.exists("AI Project", project_name):
        frappe.throw(f"AI Project does not exist: {project_name}.", frappe.PermissionError)
    if "System Manager" in frappe.get_roles():
        return
    owner = frappe.db.get_value("AI Project", project_name, "owner")
    if owner != frappe.session.user:
        frappe.throw(
            f"You do not have access to AI Project: {project_name}.",
            frappe.PermissionError,
        )


def _run_filters(project: str | None) -> dict[str, Any] | None:
    project_name = str(project or "").strip()
    if project_name:
        _assert_project_access(project_name)
        return {"project": project_name}
    if "System Manager" in frappe.get_roles():
        return {}
    projects = frappe.get_all("AI Project", filters={"owner": frappe.session.user}, pluck="name")
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
        "provider_summary": _provider_summary_for_run(row.get("name")),
        "cost_summary": _cost_summary(_ledger_summaries(row.get("name"))),
        "asset_count": frappe.db.count("AI Asset", {"source_workflow_run": row.get("name")}) if row.get("name") else 0,
    }


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
        "output": output,
        "asset_names": _asset_names_from_value(output),
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
    for row in ledger_rows:
        amount = _as_decimal(row.get("amount_usd"))
        if row.get("ledger_type") == "DEBIT":
            debits += amount
        elif row.get("ledger_type") == "CREDIT":
            credits += amount
        elif row.get("ledger_type") == "ADJUSTMENT":
            adjustments += amount
    return {
        "currency": "USD",
        "debits_usd": str(debits),
        "credits_usd": str(credits),
        "adjustments_usd": str(adjustments),
        "net_usd": str(credits + adjustments - debits),
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
    return _sanitize_error(message)


def _sanitize_error(value: Any) -> str:
    message = str(value or "Run failed.")
    message = re.sub(r"Bearer\s+[A-Za-z0-9._:-]+", "Bearer [redacted]", message)
    message = re.sub(r"(?i)(api[_-]?key|token|secret|authorization)\s*[:=]\s*[^,\s}]+", r"\1=[redacted]", message)
    return message[:240]


def _loads_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default
    return value


def _asset_names_from_value(value: Any) -> list[str]:
    names: set[str] = set()
    _collect_asset_names(value, names)
    return sorted(names)


def _collect_asset_names(value: Any, names: set[str]) -> None:
    if isinstance(value, str) and value.startswith("AI-ASSET-"):
        names.add(value)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_asset_names(item, names)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_asset_names(item, names)


def _as_limit(value: int | str) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 50
    return max(1, min(limit, 100))


def _as_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _decimal_string(value: Any) -> str:
    return str(_as_decimal(value))

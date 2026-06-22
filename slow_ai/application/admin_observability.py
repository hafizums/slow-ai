"""System Manager-only safe observability services."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import frappe
from frappe.utils import add_to_date
from frappe.utils import now_datetime

from slow_ai.application.project_access import is_system_manager


ACTIVE_RUN_STATUSES = ("QUEUED", "RUNNING", "WAITING_PROVIDER")
ACTIVE_PROVIDER_JOB_STATUSES = ("QUEUED", "SUBMITTING", "SUBMITTED", "WAITING_PROVIDER")


def get_system_overview() -> dict[str, Any]:
    """Return high-level operational counts without exposing raw provider data."""

    _assert_system_manager()
    stale_cutoff = add_to_date(now_datetime(), hours=-1)
    return {
        "workflow_runs": {
            "by_status": _count_by("AI Workflow Run", "status"),
            "active_count": frappe.db.count("AI Workflow Run", {"status": ["in", ACTIVE_RUN_STATUSES]}),
            "stale_waiting_provider_count": frappe.db.count(
                "AI Workflow Run",
                {"status": "WAITING_PROVIDER", "modified": ["<=", stale_cutoff]},
            ),
        },
        "provider_jobs": {
            "by_status": _count_by("AI Provider Job", "status"),
            "active_count": frappe.db.count("AI Provider Job", {"status": ["in", ACTIVE_PROVIDER_JOB_STATUSES]}),
            "stale_waiting_provider_count": frappe.db.count(
                "AI Provider Job",
                {"status": "WAITING_PROVIDER", "modified": ["<=", stale_cutoff]},
            ),
        },
        "billing": _billing_overview(),
        "models": {"by_status": _count_by("AI Model", "status")},
        "provider_accounts": {"by_status": _count_by("AI Provider Account", "status")},
        "shares": {
            "by_status": _count_by("AI Tool Run Share", "status"),
            "expired_active_count": frappe.db.count(
                "AI Tool Run Share",
                {"status": "ACTIVE", "expires_at": ["<", now_datetime()]},
            ),
        },
    }


def list_run_health(status: str | None = None, limit: int | str = 50) -> dict[str, Any]:
    """List safe workflow run health rows for System Managers."""

    _assert_system_manager()
    filters: dict[str, Any] = {}
    status_filter = _clean_optional(status)
    if status_filter and status_filter.upper() != "ALL":
        filters["status"] = status_filter.upper()
    rows = frappe.get_all(
        "AI Workflow Run",
        filters=filters,
        fields=[
            "name",
            "workflow",
            "workflow_version",
            "project",
            "status",
            "queued_at",
            "started_at",
            "completed_at",
            "is_archived",
            "archived_at",
            "source_template",
            "source_template_version",
            "creation",
            "modified",
        ],
        order_by="modified desc",
        limit=_as_limit(limit),
    )
    result = []
    for row in rows:
        result.append(
            {
                "workflow_run": row.name,
                "workflow": row.workflow,
                "workflow_version": row.workflow_version,
                "project": row.project,
                "status": row.status,
                "queued_at": row.queued_at,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
                "is_archived": 1 if row.is_archived else 0,
                "archived_at": row.archived_at,
                "source_template": row.source_template,
                "source_template_version": row.source_template_version,
                "node_run_count": frappe.db.count("AI Node Run", {"workflow_run": row.name}),
                "provider_job_count": _provider_job_count_for_run(row.name),
                "asset_count": frappe.db.count("AI Asset", {"source_workflow_run": row.name}),
                "ledger_count": frappe.db.count("AI Credit Ledger", {"workflow_run": row.name}),
                "created": row.creation,
                "modified": row.modified,
            }
        )
    return {"runs": result}


def list_provider_job_health(status: str | None = None, limit: int | str = 50) -> dict[str, Any]:
    """List safe provider job health rows without credentials or raw payloads."""

    _assert_system_manager()
    filters: dict[str, Any] = {}
    status_filter = _clean_optional(status)
    if status_filter and status_filter.upper() != "ALL":
        filters["status"] = status_filter.upper()
    rows = frappe.get_all(
        "AI Provider Job",
        filters=filters,
        fields=[
            "name",
            "node_run",
            "provider",
            "model",
            "status",
            "estimated_cost_usd",
            "cost_usd",
            "debit_cost_usd",
            "debit_cost_source",
            "submitted_at",
            "completed_at",
            "last_polled_at",
            "poll_attempts",
            "max_poll_attempts",
            "creation",
            "modified",
        ],
        order_by="modified desc",
        limit=_as_limit(limit),
    )
    return {
        "provider_jobs": [
            {
                "provider_job": row.name,
                "node_run": row.node_run,
                "workflow_run": frappe.db.get_value("AI Node Run", row.node_run, "workflow_run") if row.node_run else None,
                "provider": row.provider,
                "model": row.model,
                "status": row.status,
                "estimated_cost_usd": _amount(row.estimated_cost_usd),
                "cost_usd": _amount(row.cost_usd),
                "debit_cost_usd": _amount(row.debit_cost_usd),
                "debit_cost_source": row.debit_cost_source,
                "submitted_at": row.submitted_at,
                "completed_at": row.completed_at,
                "last_polled_at": row.last_polled_at,
                "poll_attempts": int(row.poll_attempts or 0),
                "max_poll_attempts": int(row.max_poll_attempts or 0),
                "created": row.creation,
                "modified": row.modified,
            }
            for row in rows
        ]
    }


def list_billing_health(limit: int | str = 50) -> dict[str, Any]:
    """Return safe project billing summaries derived from ledger rows."""

    _assert_system_manager()
    projects = frappe.get_all("AI Project", fields=["name", "project_name", "status"], order_by="modified desc", limit=_as_limit(limit))
    return {"projects": [_project_billing_summary(row) for row in projects]}


def _assert_system_manager() -> None:
    if not is_system_manager():
        frappe.throw("System Manager role is required for Slow AI observability.", frappe.PermissionError)


def _count_by(doctype: str, fieldname: str) -> dict[str, int]:
    rows = frappe.get_all(
        doctype,
        fields=[fieldname, "count(name) as count"],
        group_by=fieldname,
        order_by=f"{fieldname} asc",
    )
    return {str(row.get(fieldname) or "UNKNOWN"): int(row.count or 0) for row in rows}


def _billing_overview() -> dict[str, Any]:
    rows = frappe.get_all("AI Credit Ledger", fields=["ledger_type", "amount_usd"])
    totals: dict[str, Decimal] = {
        "CREDIT": Decimal("0"),
        "DEBIT": Decimal("0"),
        "RESERVE": Decimal("0"),
        "RELEASE": Decimal("0"),
        "ADJUSTMENT": Decimal("0"),
    }
    counts = {key: 0 for key in totals}
    for row in rows:
        ledger_type = str(row.ledger_type or "")
        if ledger_type not in totals:
            continue
        totals[ledger_type] += _decimal(row.amount_usd)
        counts[ledger_type] += 1
    return {
        "by_type": counts,
        "credits_usd": _format_decimal(totals["CREDIT"]),
        "debits_usd": _format_decimal(totals["DEBIT"]),
        "reserved_usd": _format_decimal(totals["RESERVE"]),
        "released_usd": _format_decimal(totals["RELEASE"]),
        "adjustments_usd": _format_decimal(totals["ADJUSTMENT"]),
        "available_balance_usd": _format_decimal(
            totals["CREDIT"] + totals["ADJUSTMENT"] + totals["RELEASE"] - totals["DEBIT"] - totals["RESERVE"]
        ),
    }


def _project_billing_summary(project) -> dict[str, Any]:
    rows = frappe.get_all(
        "AI Credit Ledger",
        filters={"project": project.name},
        fields=["ledger_type", "amount_usd", "creation"],
        order_by="creation desc",
    )
    totals: dict[str, Decimal] = {
        "CREDIT": Decimal("0"),
        "DEBIT": Decimal("0"),
        "RESERVE": Decimal("0"),
        "RELEASE": Decimal("0"),
        "ADJUSTMENT": Decimal("0"),
    }
    for row in rows:
        if row.ledger_type in totals:
            totals[row.ledger_type] += _decimal(row.amount_usd)
    return {
        "project": project.name,
        "project_name": project.project_name,
        "status": project.status,
        "credits_usd": _format_decimal(totals["CREDIT"]),
        "debits_usd": _format_decimal(totals["DEBIT"]),
        "reserved_usd": _format_decimal(totals["RESERVE"]),
        "released_usd": _format_decimal(totals["RELEASE"]),
        "adjustments_usd": _format_decimal(totals["ADJUSTMENT"]),
        "balance_usd": _format_decimal(
            totals["CREDIT"] + totals["ADJUSTMENT"] + totals["RELEASE"] - totals["DEBIT"] - totals["RESERVE"]
        ),
        "ledger_count": len(rows),
        "latest_ledger_at": rows[0].creation if rows else None,
    }


def _provider_job_count_for_run(workflow_run: str) -> int:
    node_runs = frappe.get_all("AI Node Run", filters={"workflow_run": workflow_run}, pluck="name")
    if not node_runs:
        return 0
    return frappe.db.count("AI Provider Job", {"node_run": ["in", node_runs]})


def _amount(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return _format_decimal(_decimal(value))


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _format_decimal(value: Decimal) -> str:
    return str(value.normalize()) if value else "0"


def _clean_optional(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip() or None


def _as_limit(value: int | str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 50
    return max(1, min(parsed, 200))

"""System Manager run recovery services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import frappe
from frappe.utils import add_to_date
from frappe.utils import get_datetime
from frappe.utils import now_datetime

from slow_ai.application.billing import release_run_reservations
from slow_ai.application.project_access import is_system_manager
from slow_ai.application.safe_payloads import safe_error_message
from slow_ai.domain.status import (
    NODE_TERMINAL_STATUSES,
    PROVIDER_JOB_TERMINAL_STATUSES,
    WORKFLOW_TERMINAL_STATUSES,
    NodeRunStatus,
    ProviderJobStatus,
    WorkflowRunStatus,
)
from slow_ai.infrastructure.provider_jobs import ProviderJobRepository
from slow_ai.infrastructure.queue import FrappeWorkflowQueue
from slow_ai.infrastructure.repositories import FrappeEngineRepository


RECOVERY_ERROR_TYPE = "AdminRunRecovery"


@dataclass(frozen=True)
class _RunContext:
    run: Any
    node_runs: list[Any]
    provider_jobs: list[Any]


def inspect_run_recovery(workflow_run: str, max_age_minutes: int | str = 60) -> dict[str, Any]:
    """Return safe System Manager-only recovery diagnostics for one run."""
    _assert_system_manager()
    context = _load_context(workflow_run)
    stale = _is_stale(context.run, _as_non_negative_int(max_age_minutes, 60))
    return {
        "run": _safe_run_payload(context.run),
        "node_runs": [_safe_node_payload(row) for row in context.node_runs],
        "provider_jobs": [_safe_provider_job_payload(row) for row in context.provider_jobs],
        "ledger": _ledger_summary(context.run.name),
        "recovery": {
            "is_terminal": _workflow_status(context.run) in WORKFLOW_TERMINAL_STATUSES,
            "is_stale": stale,
            "can_resume": _can_resume(context.run),
            "can_expire": _can_expire(context.run, stale),
        },
    }


def expire_stuck_run(
    workflow_run: str,
    max_age_minutes: int | str = 60,
    reason: str | None = None,
) -> dict[str, Any]:
    """Safely expire a stale active run without calling providers."""
    _assert_system_manager()
    context = _load_context(workflow_run)
    current = _workflow_status(context.run)
    if current == WorkflowRunStatus.EXPIRED:
        return inspect_run_recovery(context.run.name, max_age_minutes=max_age_minutes)
    if current in WORKFLOW_TERMINAL_STATUSES:
        frappe.throw("Terminal runs cannot be expired by recovery.", frappe.ValidationError)
    if not _is_stale(context.run, _as_non_negative_int(max_age_minutes, 60)):
        frappe.throw("Run is not stale enough for recovery expiry.", frappe.ValidationError)

    error = _recovery_error(reason or "Run expired by System Manager recovery.")
    repository = FrappeEngineRepository()
    provider_jobs = ProviderJobRepository()

    for row in context.provider_jobs:
        provider_status = ProviderJobStatus(row.status)
        if provider_status in PROVIDER_JOB_TERMINAL_STATUSES:
            continue
        provider_jobs.mark_cancelled(row.name)

    for row in context.node_runs:
        node_status = NodeRunStatus(row.status)
        if node_status in NODE_TERMINAL_STATUSES:
            continue
        repository.set_node_status(row.name, NodeRunStatus.CANCELLED, error=error)

    repository.set_workflow_status(context.run.name, WorkflowRunStatus.EXPIRED, error)
    release_run_reservations(context.run.name, description="Released reservation for admin recovery expiry")
    return inspect_run_recovery(context.run.name, max_age_minutes=max_age_minutes)


def resume_run(workflow_run: str) -> dict[str, Any]:
    """Enqueue an active run for normal worker execution."""
    _assert_system_manager()
    context = _load_context(workflow_run)
    if _workflow_status(context.run) in WORKFLOW_TERMINAL_STATUSES:
        frappe.throw("Terminal runs cannot be resumed by recovery.", frappe.ValidationError)
    queue_job_id = FrappeWorkflowQueue().enqueue_workflow_run(context.run.name)
    payload = inspect_run_recovery(context.run.name)
    payload["queue_job_id"] = queue_job_id
    return payload


def _assert_system_manager() -> None:
    if not is_system_manager():
        frappe.throw("System Manager role is required for run recovery.", frappe.PermissionError)


def _load_context(workflow_run: str) -> _RunContext:
    if not frappe.db.exists("AI Workflow Run", workflow_run):
        frappe.throw(f"AI Workflow Run does not exist: {workflow_run}.", frappe.DoesNotExistError)
    run = frappe.get_doc("AI Workflow Run", workflow_run)
    node_runs = frappe.get_all(
        "AI Node Run",
        filters={"workflow_run": run.name},
        fields=["name", "node_id", "node_type", "status", "provider_job", "error_json", "modified"],
        order_by="creation asc",
    )
    provider_jobs = []
    if node_runs:
        provider_jobs = frappe.get_all(
            "AI Provider Job",
            filters={"node_run": ["in", [row.name for row in node_runs]]},
            fields=[
                "name",
                "node_run",
                "provider",
                "model",
                "status",
                "estimated_cost_usd",
                "debit_cost_usd",
                "debit_cost_source",
                "poll_attempts",
                "last_polled_at",
                "raw_error_json",
                "modified",
            ],
            order_by="creation asc",
        )
    return _RunContext(run=run, node_runs=list(node_runs), provider_jobs=list(provider_jobs))


def _safe_run_payload(run) -> dict[str, Any]:
    return {
        "workflow_run": run.name,
        "workflow": run.workflow,
        "workflow_version": run.workflow_version,
        "project": run.project,
        "status": run.status,
        "queued_at": run.queued_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "modified": run.modified,
        "error": safe_error_message(run.error_json),
    }


def _safe_node_payload(row) -> dict[str, Any]:
    return {
        "name": row.name,
        "node_id": row.node_id,
        "node_type": row.node_type,
        "status": row.status,
        "provider_job": row.provider_job,
        "modified": row.modified,
        "error": safe_error_message(row.error_json),
    }


def _safe_provider_job_payload(row) -> dict[str, Any]:
    return {
        "name": row.name,
        "node_run": row.node_run,
        "provider": row.provider,
        "model": row.model,
        "status": row.status,
        "estimated_cost_usd": str(row.estimated_cost_usd or 0),
        "debit_cost_usd": str(row.debit_cost_usd or 0),
        "debit_cost_source": row.debit_cost_source,
        "poll_attempts": int(row.poll_attempts or 0),
        "last_polled_at": row.last_polled_at,
        "modified": row.modified,
        "error": safe_error_message(row.raw_error_json),
    }


def _ledger_summary(workflow_run: str) -> dict[str, Any]:
    rows = frappe.get_all(
        "AI Credit Ledger",
        filters={"workflow_run": workflow_run},
        fields=["ledger_type", "amount_usd"],
    )
    summary: dict[str, Any] = {
        "reserve_count": 0,
        "release_count": 0,
        "debit_count": 0,
        "reserved_usd": "0",
        "released_usd": "0",
        "debited_usd": "0",
    }
    totals = {"RESERVE": 0.0, "RELEASE": 0.0, "DEBIT": 0.0}
    for row in rows:
        if row.ledger_type not in totals:
            continue
        totals[row.ledger_type] += float(row.amount_usd or 0)
        key = {
            "RESERVE": "reserve_count",
            "RELEASE": "release_count",
            "DEBIT": "debit_count",
        }[row.ledger_type]
        summary[key] += 1
    summary["reserved_usd"] = str(totals["RESERVE"])
    summary["released_usd"] = str(totals["RELEASE"])
    summary["debited_usd"] = str(totals["DEBIT"])
    return summary


def _workflow_status(run) -> WorkflowRunStatus:
    return WorkflowRunStatus(run.status)


def _can_resume(run) -> bool:
    return _workflow_status(run) not in WORKFLOW_TERMINAL_STATUSES


def _can_expire(run, stale: bool) -> bool:
    return stale and _workflow_status(run) not in WORKFLOW_TERMINAL_STATUSES


def _is_stale(run, max_age_minutes: int) -> bool:
    reference = run.modified or run.started_at or run.queued_at or run.creation
    if not reference:
        return False
    cutoff = add_to_date(now_datetime(), minutes=-max_age_minutes)
    return get_datetime(reference) <= cutoff


def _recovery_error(message: str) -> dict[str, str]:
    return {"type": RECOVERY_ERROR_TYPE, "message": str(message or "Run recovered by administrator.")}


def _as_non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default

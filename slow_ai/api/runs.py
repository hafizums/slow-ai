"""Workflow run API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.runs import get_history as get_history_service
from slow_ai.application.runs import get_run_status as get_run_status_service
from slow_ai.application.runs import get_run_timeline as get_run_timeline_service
from slow_ai.application.runs import start_run as start_run_service
from slow_ai.application.run_recovery import expire_stuck_run as expire_stuck_run_service
from slow_ai.application.run_recovery import inspect_run_recovery as inspect_run_recovery_service
from slow_ai.application.run_recovery import resume_run as resume_run_service


@frappe.whitelist()
def start_run(workflow: str) -> dict:
    return start_run_service(workflow)


@frappe.whitelist()
def get_run_status(workflow_run: str) -> dict:
    return get_run_status_service(workflow_run)


@frappe.whitelist()
def get_history(workflow_run: str) -> dict:
    return get_history_service(workflow_run)


@frappe.whitelist()
def get_run_timeline(workflow_run: str) -> dict:
    return get_run_timeline_service(workflow_run)


@frappe.whitelist()
def inspect_run_recovery(workflow_run: str, max_age_minutes: int | str = 60) -> dict:
    return inspect_run_recovery_service(workflow_run, max_age_minutes=max_age_minutes)


@frappe.whitelist()
def expire_stuck_run(workflow_run: str, max_age_minutes: int | str = 60, reason: str | None = None) -> dict:
    return expire_stuck_run_service(workflow_run, max_age_minutes=max_age_minutes, reason=reason)


@frappe.whitelist()
def resume_run(workflow_run: str) -> dict:
    return resume_run_service(workflow_run)

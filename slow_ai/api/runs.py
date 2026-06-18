"""Workflow run API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.runs import get_history as get_history_service
from slow_ai.application.runs import get_run_status as get_run_status_service
from slow_ai.application.runs import start_run as start_run_service


@frappe.whitelist()
def start_run(workflow: str) -> dict:
    return start_run_service(workflow)


@frappe.whitelist()
def get_run_status(workflow_run: str) -> dict:
    return get_run_status_service(workflow_run)


@frappe.whitelist()
def get_history(workflow_run: str) -> dict:
    return get_history_service(workflow_run)

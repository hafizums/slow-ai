"""System Manager-only Slow AI observability API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.admin_observability import get_system_overview as get_system_overview_service
from slow_ai.application.admin_observability import list_billing_health as list_billing_health_service
from slow_ai.application.admin_observability import list_provider_job_health as list_provider_job_health_service
from slow_ai.application.admin_observability import list_run_health as list_run_health_service


@frappe.whitelist()
def get_system_overview() -> dict:
    return get_system_overview_service()


@frappe.whitelist()
def list_run_health(status=None, limit=50) -> dict:
    return list_run_health_service(status=status, limit=limit)


@frappe.whitelist()
def list_provider_job_health(status=None, limit=50) -> dict:
    return list_provider_job_health_service(status=status, limit=limit)


@frappe.whitelist()
def list_billing_health(limit=50) -> dict:
    return list_billing_health_service(limit=limit)

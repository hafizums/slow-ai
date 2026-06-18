"""Workflow queue API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.queue import get_queue_status as get_queue_status_service


@frappe.whitelist()
def get_queue_status() -> dict:
    return get_queue_status_service()

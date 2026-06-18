"""Queue status application service."""

from __future__ import annotations

from typing import Any

import frappe


def get_queue_status() -> dict[str, Any]:
    queued_runs = frappe.get_all(
        "AI Workflow Run",
        filters={"status": "QUEUED"},
        fields=["name", "workflow", "workflow_version", "project", "queued_at"],
        order_by="creation asc",
    )
    running_runs = frappe.get_all(
        "AI Workflow Run",
        filters={"status": ["in", ["RUNNING", "WAITING_PROVIDER"]]},
        fields=["name", "workflow", "workflow_version", "project", "status", "started_at"],
        order_by="modified desc",
    )
    return {
        "queued": [dict(row) for row in queued_runs],
        "running": [dict(row) for row in running_runs],
        "counts": {
            "queued": len(queued_runs),
            "running": len(running_runs),
        },
    }

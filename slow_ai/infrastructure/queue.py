"""Frappe queue adapters for slow_ai workers."""

from __future__ import annotations

import frappe


class FrappeWorkflowQueue:
    def enqueue_workflow_run(self, workflow_run_name: str) -> str:
        job_id = f"slow_ai:workflow_run:{workflow_run_name}"
        frappe.enqueue(
            "slow_ai.workers.run_workflow.run_workflow",
            queue="long",
            timeout=3600,
            enqueue_after_commit=True,
            job_id=job_id,
            workflow_run_name=workflow_run_name,
        )
        return job_id

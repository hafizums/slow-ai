"""Realtime event helpers for workflow execution state."""

from __future__ import annotations

from typing import Any, Mapping

import frappe


WORKFLOW_RUN_EVENT = "slow_ai_workflow_run_update"
NODE_RUN_EVENT = "slow_ai_node_run_update"
PROVIDER_JOB_EVENT = "slow_ai_provider_job_update"


def publish_workflow_run_update(
    workflow_run_name: str,
    status: str,
    extra: Mapping[str, Any] | None = None,
) -> None:
    message = {"workflow_run": workflow_run_name, "status": status}
    if extra:
        message.update(extra)
    frappe.publish_realtime(
        WORKFLOW_RUN_EVENT,
        message,
        doctype="AI Workflow Run",
        docname=workflow_run_name,
        after_commit=True,
    )


def publish_node_run_update(
    node_run_name: str,
    workflow_run_name: str,
    status: str,
    extra: Mapping[str, Any] | None = None,
) -> None:
    message = {
        "node_run": node_run_name,
        "workflow_run": workflow_run_name,
        "status": status,
    }
    if extra:
        message.update(extra)
    frappe.publish_realtime(
        NODE_RUN_EVENT,
        message,
        doctype="AI Workflow Run",
        docname=workflow_run_name,
        after_commit=True,
    )


def publish_provider_job_update(
    provider_job_name: str,
    status: str,
    extra: Mapping[str, Any] | None = None,
) -> None:
    message = {"provider_job": provider_job_name, "status": status}
    if extra:
        message.update(extra)
    frappe.publish_realtime(
        PROVIDER_JOB_EVENT,
        message,
        doctype="AI Provider Job",
        docname=provider_job_name,
        after_commit=True,
    )

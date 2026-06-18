"""Workflow draft API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.workflows import get_workflow as get_workflow_service
from slow_ai.application.workflows import save_workflow as save_workflow_service


@frappe.whitelist()
def save_workflow(
    project: str,
    title: str,
    nodes,
    edges,
    layout=None,
    workflow: str | None = None,
    status: str = "DRAFT",
) -> dict:
    return save_workflow_service(
        project=project,
        title=title,
        nodes=nodes,
        edges=edges,
        layout=layout,
        workflow=workflow,
        status=status,
    )


@frappe.whitelist()
def get_workflow(workflow: str) -> dict:
    return get_workflow_service(workflow)

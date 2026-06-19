"""Workflow run query application services."""

from __future__ import annotations

import json
from typing import Any

import frappe

from slow_ai.application.project_access import assert_can_view_project
from slow_ai.application.run_service import RunService
from slow_ai.application.template_lineage import safe_template_lineage


def start_run(workflow: str) -> dict[str, Any]:
    result = RunService().start_run(workflow)
    return {
        "workflow_version": result.workflow_version,
        "workflow_run": result.workflow_run,
        "node_runs": list(result.node_runs),
        "queue_job_id": result.queue_job_id,
    }


def get_run_status(workflow_run: str) -> dict[str, Any]:
    run = frappe.get_doc("AI Workflow Run", workflow_run)
    assert_can_view_project(run.project)
    node_runs = frappe.get_all(
        "AI Node Run",
        filters={"workflow_run": workflow_run},
        fields=["name", "node_id", "node_type", "status", "provider_job", "cost_usd"],
        order_by="creation asc",
    )
    return {
        "workflow_run": run.name,
        "workflow": run.workflow,
        "workflow_version": run.workflow_version,
        "project": run.project,
        "status": run.status,
        "queued_at": run.queued_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "error": _loads_json(run.error_json, None),
        "template_lineage": safe_template_lineage(
            getattr(run, "source_template", None),
            getattr(run, "source_template_version", None),
        ),
        "node_runs": [_row_dict(row) for row in node_runs],
    }


def get_history(workflow_run: str) -> dict[str, Any]:
    status = get_run_status(workflow_run)
    node_runs = frappe.get_all(
        "AI Node Run",
        filters={"workflow_run": workflow_run},
        fields=[
            "name",
            "node_id",
            "node_type",
            "status",
            "provider_job",
            "cost_usd",
            "input_json",
            "output_json",
            "error_json",
            "started_at",
            "completed_at",
        ],
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
                "provider_account",
                "model",
                "external_job_id",
                "status",
                "cost_usd",
                "estimated_cost_usd",
                "debit_cost_usd",
                "debit_cost_source",
                "submitted_at",
                "completed_at",
                "response_json",
                "raw_error_json",
            ],
            order_by="creation asc",
        )
    assets = frappe.get_all(
        "AI Asset",
        filters={"source_workflow_run": workflow_run},
        fields=[
            "name",
            "asset_type",
            "file",
            "url",
            "mime_type",
            "source_node_run",
            "source_provider_job",
            "metadata_json",
        ],
        order_by="creation asc",
    )
    ledger_entries = frappe.get_all(
        "AI Credit Ledger",
        filters={"workflow_run": workflow_run},
        fields=["name", "node_run", "provider_job", "ledger_type", "amount_usd", "currency"],
        order_by="creation asc",
    )
    return {
        "run": status,
        "node_runs": [
            {
                **_row_dict(row),
                "input": _loads_json(row.input_json, {}),
                "output": _loads_json(row.output_json, {}),
                "error": _loads_json(row.error_json, None),
            }
            for row in node_runs
        ],
        "provider_jobs": [
            {
                **_row_dict(row),
                "response": _loads_json(row.response_json, {}),
                "error": _loads_json(row.raw_error_json, None),
            }
            for row in provider_jobs
        ],
        "assets": [
            {
                **_row_dict(row),
                "metadata": _loads_json(row.metadata_json, {}),
            }
            for row in assets
        ],
        "ledger": [_row_dict(row) for row in ledger_entries],
    }


def _loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _row_dict(row) -> dict[str, Any]:
    return dict(row)

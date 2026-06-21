"""Workflow run query application services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
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


def get_run_timeline(workflow_run: str) -> dict[str, Any]:
    run = frappe.get_doc("AI Workflow Run", workflow_run)
    assert_can_view_project(run.project)

    events: list[_TimelineEvent] = []
    _add_run_events(events, run)

    node_runs = frappe.get_all(
        "AI Node Run",
        filters={"workflow_run": workflow_run},
        fields=[
            "name",
            "node_id",
            "node_type",
            "status",
            "provider_job",
            "started_at",
            "completed_at",
            "creation",
            "modified",
        ],
        order_by="creation asc",
    )
    node_run_names = [row.name for row in node_runs]
    node_run_by_name = {row.name: row for row in node_runs}
    for node_run in node_runs:
        _add_node_events(events, node_run)

    provider_jobs = []
    if node_run_names:
        provider_jobs = frappe.get_all(
            "AI Provider Job",
            filters={"node_run": ["in", node_run_names]},
            fields=[
                "name",
                "node_run",
                "status",
                "submitted_at",
                "completed_at",
                "last_polled_at",
                "poll_attempts",
                "creation",
                "modified",
            ],
            order_by="creation asc",
        )
    for provider_job in provider_jobs:
        _add_provider_job_events(events, provider_job, node_run_by_name.get(provider_job.node_run))

    assets = frappe.get_all(
        "AI Asset",
        filters={"source_workflow_run": workflow_run},
        fields=[
            "name",
            "asset_type",
            "source_node_run",
            "source_provider_job",
            "creation",
            "modified",
        ],
        order_by="creation asc",
    )
    for asset in assets:
        _add_asset_event(events, asset, node_run_by_name.get(asset.source_node_run))

    ledger_entries = frappe.get_all(
        "AI Credit Ledger",
        filters={"workflow_run": workflow_run},
        fields=[
            "name",
            "node_run",
            "provider_job",
            "ledger_type",
            "amount_usd",
            "currency",
            "creation",
            "modified",
        ],
        order_by="creation asc",
    )
    for ledger_entry in ledger_entries:
        _add_ledger_event(events, ledger_entry, node_run_by_name.get(ledger_entry.node_run))

    share_events = frappe.get_all(
        "AI Tool Run Share",
        filters={"workflow_run": workflow_run},
        fields=["name", "status", "creation", "modified"],
        order_by="creation asc",
    )
    for share in share_events:
        _add_share_event(events, share)

    events.sort(key=lambda event: (str(event.timestamp or ""), event.sequence))

    return {
        "run": {
            "workflow_run": run.name,
            "workflow": run.workflow,
            "workflow_version": run.workflow_version,
            "project": run.project,
            "status": run.status,
            "queued_at": run.queued_at,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "is_archived": 1 if getattr(run, "is_archived", 0) else 0,
            "archived_at": getattr(run, "archived_at", None),
            "template_lineage": safe_template_lineage(
                getattr(run, "source_template", None),
                getattr(run, "source_template_version", None),
            ),
        },
        "events": [event.as_dict() for event in events],
        "summary": {
            "event_count": len(events),
            "node_run_count": len(node_runs),
            "provider_job_count": len(provider_jobs),
            "asset_count": len(assets),
            "ledger_count": len(ledger_entries),
            "share_count": len(share_events),
        },
    }


def _loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _row_dict(row) -> dict[str, Any]:
    return dict(row)


@dataclass
class _TimelineEvent:
    sequence: int
    timestamp: Any
    event_type: str
    title: str
    message: str
    related_doctype: str | None = None
    related_name: str | None = None
    node_id: str | None = None
    node_type: str | None = None
    status: str | None = None
    amount_usd: str | None = None
    currency: str | None = None

    def as_dict(self) -> dict[str, Any]:
        event = {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "title": self.title,
            "message": self.message,
        }
        optional = {
            "related_doctype": self.related_doctype,
            "related_name": self.related_name,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "status": self.status,
            "amount_usd": self.amount_usd,
            "currency": self.currency,
        }
        event.update({key: value for key, value in optional.items() if value not in (None, "")})
        return event


def _append_event(events: list[_TimelineEvent], **kwargs) -> None:
    events.append(_TimelineEvent(sequence=len(events), **kwargs))


def _add_run_events(events: list[_TimelineEvent], run) -> None:
    _append_event(
        events,
        timestamp=run.queued_at or run.creation,
        event_type="RUN_QUEUED",
        title="Run queued",
        message="Workflow run was queued.",
        related_doctype="AI Workflow Run",
        related_name=run.name,
        status=run.status,
    )
    if run.started_at:
        _append_event(
            events,
            timestamp=run.started_at,
            event_type="RUN_STARTED",
            title="Run started",
            message="Workflow run started.",
            related_doctype="AI Workflow Run",
            related_name=run.name,
            status=run.status,
        )

    terminal_event = {
        "SUCCEEDED": ("RUN_SUCCEEDED", "Run succeeded", "Workflow run completed successfully."),
        "FAILED": ("RUN_FAILED", "Run failed", "Workflow run failed."),
        "CANCELLED": ("RUN_CANCELLED", "Run cancelled", "Workflow run was cancelled."),
        "EXPIRED": ("RUN_EXPIRED", "Run expired", "Workflow run expired."),
    }.get(run.status)
    if terminal_event:
        event_type, title, message = terminal_event
        _append_event(
            events,
            timestamp=run.completed_at or run.modified,
            event_type=event_type,
            title=title,
            message=message,
            related_doctype="AI Workflow Run",
            related_name=run.name,
            status=run.status,
        )

    if getattr(run, "is_archived", 0):
        _append_event(
            events,
            timestamp=getattr(run, "archived_at", None) or run.modified,
            event_type="RUN_ARCHIVED",
            title="Run archived",
            message="Workflow run was archived from the default library view.",
            related_doctype="AI Workflow Run",
            related_name=run.name,
            status=run.status,
        )


def _add_node_events(events: list[_TimelineEvent], node_run) -> None:
    if node_run.started_at:
        _append_event(
            events,
            timestamp=node_run.started_at,
            event_type="NODE_STARTED",
            title="Node started",
            message=f"Node {node_run.node_id} started.",
            related_doctype="AI Node Run",
            related_name=node_run.name,
            node_id=node_run.node_id,
            node_type=node_run.node_type,
            status=node_run.status,
        )


def _add_provider_job_events(events: list[_TimelineEvent], provider_job, node_run) -> None:
    node_context = _node_context(node_run)
    _append_event(
        events,
        timestamp=provider_job.creation,
        event_type="PROVIDER_JOB_CREATED",
        title="Provider job created",
        message="Provider job record was created.",
        related_doctype="AI Provider Job",
        related_name=provider_job.name,
        status=provider_job.status,
        **node_context,
    )
    if provider_job.submitted_at:
        _append_event(
            events,
            timestamp=provider_job.submitted_at,
            event_type="PROVIDER_JOB_SUBMITTED",
            title="Provider job submitted",
            message="Provider job was submitted by the backend worker.",
            related_doctype="AI Provider Job",
            related_name=provider_job.name,
            status=provider_job.status,
            **node_context,
        )
    if provider_job.last_polled_at and int(provider_job.poll_attempts or 0) > 0:
        _append_event(
            events,
            timestamp=provider_job.last_polled_at,
            event_type="PROVIDER_JOB_POLLED",
            title="Provider job polled",
            message="Provider job status was checked by the backend poller.",
            related_doctype="AI Provider Job",
            related_name=provider_job.name,
            status=provider_job.status,
            **node_context,
        )

    terminal_event = {
        "SUCCEEDED": ("PROVIDER_JOB_SUCCEEDED", "Provider job succeeded", "Provider job completed successfully."),
        "FAILED": ("PROVIDER_JOB_FAILED", "Provider job failed", "Provider job failed safely."),
        "EXPIRED": ("PROVIDER_JOB_EXPIRED", "Provider job expired", "Provider job exceeded its polling policy."),
        "CANCELLED": ("PROVIDER_JOB_FAILED", "Provider job cancelled", "Provider job was cancelled locally."),
    }.get(provider_job.status)
    if terminal_event:
        event_type, title, message = terminal_event
        _append_event(
            events,
            timestamp=provider_job.completed_at or provider_job.modified,
            event_type=event_type,
            title=title,
            message=message,
            related_doctype="AI Provider Job",
            related_name=provider_job.name,
            status=provider_job.status,
            **node_context,
        )


def _add_asset_event(events: list[_TimelineEvent], asset, node_run) -> None:
    _append_event(
        events,
        timestamp=asset.creation,
        event_type="ASSET_CREATED",
        title="Asset created",
        message=f"{asset.asset_type} asset was created.",
        related_doctype="AI Asset",
        related_name=asset.name,
        node_id=getattr(node_run, "node_id", None),
        node_type=getattr(node_run, "node_type", None),
        status=asset.asset_type,
    )


def _add_ledger_event(events: list[_TimelineEvent], ledger_entry, node_run) -> None:
    event_meta = {
        "RESERVE": ("CREDIT_RESERVED", "Credit reserved", "Estimated credits were reserved."),
        "RELEASE": ("CREDIT_RELEASED", "Credit released", "Reserved credits were released."),
        "DEBIT": ("CREDIT_DEBITED", "Credit debited", "Provider cost was debited."),
        "CREDIT": ("CREDIT_ADDED", "Credit added", "Credits were added."),
        "ADJUSTMENT": ("CREDIT_ADJUSTED", "Credit adjusted", "Credit balance was adjusted."),
    }.get(ledger_entry.ledger_type)
    if not event_meta:
        return
    event_type, title, message = event_meta
    _append_event(
        events,
        timestamp=ledger_entry.creation,
        event_type=event_type,
        title=title,
        message=message,
        related_doctype="AI Credit Ledger",
        related_name=ledger_entry.name,
        node_id=getattr(node_run, "node_id", None),
        node_type=getattr(node_run, "node_type", None),
        status=ledger_entry.ledger_type,
        amount_usd=_format_amount(ledger_entry.amount_usd),
        currency=ledger_entry.currency or "USD",
    )


def _add_share_event(events: list[_TimelineEvent], share) -> None:
    _append_event(
        events,
        timestamp=share.creation,
        event_type="RUN_SHARED",
        title="Share link created",
        message="A read-only share link was created for this run.",
        related_doctype="AI Tool Run Share",
        related_name=share.name,
        status=share.status,
    )
    if share.status == "DISABLED":
        _append_event(
            events,
            timestamp=share.modified,
            event_type="RUN_SHARE_DISABLED",
            title="Share link disabled",
            message="A read-only share link was disabled.",
            related_doctype="AI Tool Run Share",
            related_name=share.name,
            status=share.status,
        )


def _node_context(node_run) -> dict[str, str | None]:
    if not node_run:
        return {"node_id": None, "node_type": None}
    return {"node_id": node_run.node_id, "node_type": node_run.node_type}


def _format_amount(value: Any) -> str:
    return str(Decimal(str(value or 0)).quantize(Decimal("0.0001")))

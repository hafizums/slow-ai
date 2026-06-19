"""Provider job polling worker entrypoint."""

from __future__ import annotations

import frappe

from slow_ai.domain.status import (
    NODE_TERMINAL_STATUSES,
    PROVIDER_JOB_TERMINAL_STATUSES,
    NodeRunStatus,
    ProviderJobStatus,
    WorkflowRunStatus,
)
from slow_ai.infrastructure.provider_jobs import ProviderJobRepository
from slow_ai.infrastructure.provider_outputs import ProviderOutputService
from slow_ai.infrastructure.queue import FrappeWorkflowQueue
from slow_ai.infrastructure.repositories import FrappeEngineRepository
from slow_ai.providers.registry import ProviderRegistry, create_default_provider_registry


POLLABLE_PROVIDER_JOB_STATUSES = (
    ProviderJobStatus.SUBMITTED.value,
    ProviderJobStatus.WAITING_PROVIDER.value,
)


def poll_pending_provider_jobs(
    limit: int = 20,
    provider: str | None = None,
    provider_registry: ProviderRegistry | None = None,
) -> dict:
    """Poll persisted provider jobs that are waiting on external providers."""
    filters: dict = {"status": ["in", POLLABLE_PROVIDER_JOB_STATUSES]}
    if provider:
        filters["provider"] = provider
    rows = frappe.get_all(
        "AI Provider Job",
        filters=filters,
        fields=["name", "external_job_id"],
        order_by="modified asc",
        limit=max(int(limit), 1),
    )
    registry = provider_registry or create_default_provider_registry()
    polled: list[dict] = []
    skipped: list[str] = []
    errors: list[dict] = []

    for row in rows:
        if not row.external_job_id:
            skipped.append(row.name)
            continue
        try:
            polled.append(
                poll_provider_job(
                    row.name,
                    provider_registry=registry,
                    enqueue_resume=True,
                )
            )
        except Exception:
            errors.append({"provider_job": row.name, "error": "Polling failed. See Error Log."})
            frappe.log_error(
                title=f"Slow AI provider polling failed: {row.name}",
                message=frappe.get_traceback(),
            )

    return {
        "polled": polled,
        "skipped": skipped,
        "errors": errors,
    }


def poll_provider_job(
    provider_job_name: str,
    provider_registry: ProviderRegistry | None = None,
    *,
    enqueue_resume: bool = True,
) -> dict:
    """Poll one persisted provider job and optionally enqueue workflow resume."""
    provider_jobs = ProviderJobRepository()
    provider_job = provider_jobs.get(provider_job_name)
    workflow_run = frappe.db.get_value("AI Node Run", provider_job.node_run, "workflow_run") if provider_job.node_run else None
    if workflow_run and frappe.db.get_value("AI Workflow Run", workflow_run, "status") == WorkflowRunStatus.CANCELLED.value:
        return _stop_polling_cancelled_run(provider_job, workflow_run, provider_jobs)

    registry = provider_registry or create_default_provider_registry()
    result = registry.get(provider_job.provider).poll_job(provider_job.name)
    provider_job = provider_jobs.get(provider_job_name)

    if provider_job.node_run:
        workflow_run = frappe.db.get_value("AI Node Run", provider_job.node_run, "workflow_run")
        _update_waiting_node_from_provider_result(provider_job, result, workflow_run)

    target_status = ProviderJobStatus(result.status)
    if enqueue_resume and target_status in PROVIDER_JOB_TERMINAL_STATUSES and provider_job.node_run:
        if workflow_run:
            queue_job_id = FrappeWorkflowQueue().enqueue_workflow_run(workflow_run)
        else:
            queue_job_id = None
    else:
        queue_job_id = None

    return {
        "provider_job": provider_job_name,
        "status": result.status,
        "external_job_id": result.external_job_id,
        "queue_job_id": queue_job_id,
    }


def _stop_polling_cancelled_run(provider_job, workflow_run: str, provider_jobs: ProviderJobRepository) -> dict:
    repository = FrappeEngineRepository()
    if provider_job.status not in {status.value for status in PROVIDER_JOB_TERMINAL_STATUSES}:
        provider_jobs.mark_cancelled(provider_job.name)
        provider_job = provider_jobs.get(provider_job.name)

    if provider_job.node_run:
        node_run = repository.get_node_run(provider_job.node_run)
        if NodeRunStatus(node_run.status) not in NODE_TERMINAL_STATUSES:
            repository.set_node_status(
                node_run.name,
                status=NodeRunStatus.CANCELLED,
                error={"type": "RunCancelled", "message": "Run cancelled by user."},
                provider_job_name=provider_job.name,
            )

    return {
        "provider_job": provider_job.name,
        "status": provider_job.status,
        "external_job_id": provider_job.external_job_id,
        "queue_job_id": None,
    }


def _update_waiting_node_from_provider_result(provider_job, result, workflow_run: str | None) -> None:
    if not workflow_run:
        return
    repository = FrappeEngineRepository()
    node_run = repository.get_node_run(provider_job.node_run)
    if node_run.status != "WAITING_PROVIDER":
        return

    target_status = ProviderJobStatus(result.status)
    if target_status == ProviderJobStatus.SUCCEEDED:
        materialized = ProviderOutputService().materialize(
            project_name=frappe.db.get_value("AI Workflow Run", workflow_run, "project"),
            workflow_run_name=workflow_run,
            node_run_name=node_run.name,
            provider_job_name=provider_job.name,
            result=result,
            description=f"{node_run.node_type} provider cost",
        )
        repository.set_node_status(
            node_run.name,
            status=NodeRunStatus.SUCCEEDED,
            outputs=materialized.node_outputs,
            cost_usd=materialized.debit_amount_usd,
            provider_job_name=provider_job.name,
        )
        return

    if target_status == ProviderJobStatus.CANCELLED:
        repository.set_node_status(
            node_run.name,
            status=NodeRunStatus.CANCELLED,
            error=result.error,
            provider_job_name=provider_job.name,
        )
        return

    if target_status in {ProviderJobStatus.FAILED, ProviderJobStatus.EXPIRED}:
        repository.set_node_status(
            node_run.name,
            status=NodeRunStatus.FAILED,
            error=result.error or {"message": f"Provider job ended with status {result.status}."},
            provider_job_name=provider_job.name,
        )

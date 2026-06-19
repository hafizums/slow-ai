"""Provider job polling worker entrypoint."""

from __future__ import annotations

import json

import frappe

from slow_ai.domain.status import (
    NODE_TERMINAL_STATUSES,
    PROVIDER_JOB_TERMINAL_STATUSES,
    WORKFLOW_TERMINAL_STATUSES,
    NodeRunStatus,
    ProviderJobStatus,
    WorkflowRunStatus,
)
from slow_ai.infrastructure.provider_jobs import ProviderJobRepository
from slow_ai.infrastructure.provider_outputs import ProviderOutputService
from slow_ai.infrastructure.queue import FrappeWorkflowQueue
from slow_ai.infrastructure.repositories import FrappeEngineRepository
from slow_ai.providers.contracts import NormalizedProviderResult
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
    workflow_status = frappe.db.get_value("AI Workflow Run", workflow_run, "status") if workflow_run else None
    if workflow_status == WorkflowRunStatus.CANCELLED.value:
        return _stop_polling_cancelled_run(provider_job, workflow_run, provider_jobs)
    if workflow_status and WorkflowRunStatus(workflow_status) in WORKFLOW_TERMINAL_STATUSES:
        return {
            "provider_job": provider_job_name,
            "status": provider_job.status,
            "external_job_id": provider_job.external_job_id,
            "queue_job_id": None,
        }

    registry = provider_registry or create_default_provider_registry()
    if ProviderJobStatus(provider_job.status) in PROVIDER_JOB_TERMINAL_STATUSES:
        queue_job_id = _recover_terminal_provider_job(
            provider_job,
            workflow_run,
            registry,
            enqueue_resume=enqueue_resume,
        )
        return {
            "provider_job": provider_job_name,
            "status": provider_job.status,
            "external_job_id": provider_job.external_job_id,
            "queue_job_id": queue_job_id,
        }

    result = registry.get(provider_job.provider).poll_job(provider_job.name)
    provider_job = provider_jobs.get(provider_job_name)

    if provider_job.node_run:
        workflow_run = frappe.db.get_value("AI Node Run", provider_job.node_run, "workflow_run")
        _update_waiting_node_from_provider_result(provider_job, result, workflow_run)

    target_status = ProviderJobStatus(result.status)
    if (
        enqueue_resume
        and target_status in PROVIDER_JOB_TERMINAL_STATUSES
        and provider_job.node_run
        and _workflow_can_resume(workflow_run)
    ):
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


def _recover_terminal_provider_job(
    provider_job,
    workflow_run: str | None,
    registry: ProviderRegistry,
    *,
    enqueue_resume: bool,
) -> str | None:
    if not provider_job.node_run or not workflow_run:
        return None
    node_status = frappe.db.get_value("AI Node Run", provider_job.node_run, "status")
    if node_status != NodeRunStatus.WAITING_PROVIDER.value:
        return None

    result = _result_from_terminal_provider_job(provider_job, registry)
    _update_waiting_node_from_provider_result(provider_job, result, workflow_run)
    if enqueue_resume and ProviderJobStatus(provider_job.status) in PROVIDER_JOB_TERMINAL_STATUSES:
        if _workflow_can_resume(workflow_run):
            return FrappeWorkflowQueue().enqueue_workflow_run(workflow_run)
    return None


def _result_from_terminal_provider_job(provider_job, registry: ProviderRegistry) -> NormalizedProviderResult:
    raw_response = _loads_json(provider_job.response_json, {})
    if raw_response:
        result = registry.get(provider_job.provider).normalize_result(raw_response)
        if result.status == provider_job.status:
            return result
    return NormalizedProviderResult(
        status=provider_job.status,
        external_job_id=provider_job.external_job_id,
        cost_usd=float(provider_job.cost_usd or 0),
        error=_loads_json(provider_job.raw_error_json, None),
    )


def _workflow_can_resume(workflow_run: str | None) -> bool:
    if not workflow_run:
        return False
    status = frappe.db.get_value("AI Workflow Run", workflow_run, "status")
    if not status:
        return False
    return WorkflowRunStatus(status) not in WORKFLOW_TERMINAL_STATUSES


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


def _loads_json(value: str | None, default):
    if not value:
        return default
    return json.loads(value)

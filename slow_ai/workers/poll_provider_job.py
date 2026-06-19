"""Provider job polling worker entrypoint."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime

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
DEFAULT_MAX_POLL_ATTEMPTS = 120
DEFAULT_PROVIDER_JOB_TIMEOUT_SECONDS = 3600


@dataclass(frozen=True)
class ProviderJobPollPolicyViolation:
    error_type: str
    message: str

    def as_error(self) -> dict[str, str]:
        return {"type": self.error_type, "message": self.message}


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

    violation = _poll_policy_violation(provider_job)
    if violation:
        return _expire_provider_job(provider_job, workflow_run, provider_jobs, violation.as_error())

    provider_jobs.record_poll_attempt(provider_job.name)
    result = registry.get(provider_job.provider).poll_job(provider_job.name)
    provider_job = provider_jobs.get(provider_job_name)

    if provider_job.node_run:
        workflow_run = frappe.db.get_value("AI Node Run", provider_job.node_run, "workflow_run")
        _update_waiting_node_from_provider_result(provider_job, result, workflow_run)

    target_status = ProviderJobStatus(result.status)
    if target_status not in PROVIDER_JOB_TERMINAL_STATUSES:
        violation = _poll_policy_violation(provider_job)
        if violation:
            return _expire_provider_job(provider_job, workflow_run, provider_jobs, violation.as_error())

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


def _poll_policy_violation(provider_job) -> ProviderJobPollPolicyViolation | None:
    max_attempts = _as_non_negative_int(
        getattr(provider_job, "max_poll_attempts", None),
        DEFAULT_MAX_POLL_ATTEMPTS,
    )
    poll_attempts = _as_non_negative_int(getattr(provider_job, "poll_attempts", None), 0)
    if max_attempts == 0 or poll_attempts >= max_attempts:
        return ProviderJobPollPolicyViolation(
            error_type="ProviderJobMaxPollAttemptsExceeded",
            message=f"Provider job exceeded max poll attempts ({max_attempts}).",
        )

    timeout_seconds = _as_non_negative_int(
        getattr(provider_job, "timeout_seconds", None),
        DEFAULT_PROVIDER_JOB_TIMEOUT_SECONDS,
    )
    if timeout_seconds == 0:
        return ProviderJobPollPolicyViolation(
            error_type="ProviderJobTimeout",
            message="Provider job timed out before completion.",
        )
    submitted_at = getattr(provider_job, "submitted_at", None) or getattr(provider_job, "creation", None)
    if submitted_at and get_datetime(submitted_at) + timedelta(seconds=timeout_seconds) <= now_datetime():
        return ProviderJobPollPolicyViolation(
            error_type="ProviderJobTimeout",
            message="Provider job timed out before completion.",
        )
    return None


def _expire_provider_job(
    provider_job,
    workflow_run: str | None,
    provider_jobs: ProviderJobRepository,
    error: dict[str, str],
) -> dict:
    provider_jobs.mark_expired(provider_job.name, error)
    provider_job = provider_jobs.get(provider_job.name)
    _mark_timed_out_node_and_workflow(provider_job, workflow_run, error)
    return {
        "provider_job": provider_job.name,
        "status": provider_job.status,
        "external_job_id": provider_job.external_job_id,
        "queue_job_id": None,
    }


def _mark_timed_out_node_and_workflow(provider_job, workflow_run: str | None, error: dict[str, str]) -> None:
    repository = FrappeEngineRepository()
    if provider_job.node_run:
        node_run = repository.get_node_run(provider_job.node_run)
        current_node_status = NodeRunStatus(node_run.status)
        if current_node_status not in NODE_TERMINAL_STATUSES:
            if current_node_status in {
                NodeRunStatus.PENDING,
                NodeRunStatus.RUNNING,
                NodeRunStatus.WAITING_PROVIDER,
            }:
                repository.set_node_status(
                    node_run.name,
                    status=NodeRunStatus.FAILED,
                    error=error,
                    provider_job_name=provider_job.name,
                )

    if not workflow_run:
        return
    current_workflow_status_value = frappe.db.get_value("AI Workflow Run", workflow_run, "status")
    if not current_workflow_status_value:
        return
    current_workflow_status = WorkflowRunStatus(current_workflow_status_value)
    if current_workflow_status in WORKFLOW_TERMINAL_STATUSES:
        return
    if current_workflow_status == WorkflowRunStatus.WAITING_PROVIDER:
        repository.set_workflow_status(workflow_run, WorkflowRunStatus.EXPIRED, error)
        return
    if current_workflow_status in {WorkflowRunStatus.QUEUED, WorkflowRunStatus.RUNNING}:
        repository.set_workflow_status(workflow_run, WorkflowRunStatus.FAILED, error)


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


def _as_non_negative_int(value, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default

"""Run state transition rules."""

from __future__ import annotations

from enum import Enum

from slow_ai.domain.exceptions import StateTransitionError
from slow_ai.domain.status import NodeRunStatus, ProviderJobStatus, WorkflowRunStatus


WORKFLOW_RUN_TRANSITIONS = {
    WorkflowRunStatus.DRAFT: frozenset({WorkflowRunStatus.QUEUED}),
    WorkflowRunStatus.QUEUED: frozenset(
        {WorkflowRunStatus.RUNNING, WorkflowRunStatus.CANCELLED, WorkflowRunStatus.FAILED}
    ),
    WorkflowRunStatus.RUNNING: frozenset(
        {
            WorkflowRunStatus.WAITING_PROVIDER,
            WorkflowRunStatus.SUCCEEDED,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.CANCELLED,
        }
    ),
    WorkflowRunStatus.WAITING_PROVIDER: frozenset(
        {
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.SUCCEEDED,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.CANCELLED,
            WorkflowRunStatus.EXPIRED,
        }
    ),
    WorkflowRunStatus.SUCCEEDED: frozenset(),
    WorkflowRunStatus.FAILED: frozenset(),
    WorkflowRunStatus.CANCELLED: frozenset(),
    WorkflowRunStatus.EXPIRED: frozenset(),
}

NODE_RUN_TRANSITIONS = {
    NodeRunStatus.PENDING: frozenset(
        {NodeRunStatus.READY, NodeRunStatus.SKIPPED, NodeRunStatus.CANCELLED, NodeRunStatus.FAILED}
    ),
    NodeRunStatus.READY: frozenset({NodeRunStatus.RUNNING, NodeRunStatus.CANCELLED}),
    NodeRunStatus.RUNNING: frozenset(
        {
            NodeRunStatus.WAITING_PROVIDER,
            NodeRunStatus.SUCCEEDED,
            NodeRunStatus.FAILED,
            NodeRunStatus.CANCELLED,
        }
    ),
    NodeRunStatus.WAITING_PROVIDER: frozenset(
        {
            NodeRunStatus.RUNNING,
            NodeRunStatus.SUCCEEDED,
            NodeRunStatus.FAILED,
            NodeRunStatus.CANCELLED,
        }
    ),
    NodeRunStatus.SUCCEEDED: frozenset(),
    NodeRunStatus.FAILED: frozenset(),
    NodeRunStatus.SKIPPED: frozenset(),
    NodeRunStatus.CANCELLED: frozenset(),
}

PROVIDER_JOB_TRANSITIONS = {
    ProviderJobStatus.QUEUED: frozenset(
        {ProviderJobStatus.SUBMITTING, ProviderJobStatus.CANCELLED}
    ),
    ProviderJobStatus.SUBMITTING: frozenset(
        {ProviderJobStatus.SUBMITTED, ProviderJobStatus.FAILED, ProviderJobStatus.CANCELLED}
    ),
    ProviderJobStatus.SUBMITTED: frozenset(
        {
            ProviderJobStatus.WAITING_PROVIDER,
            ProviderJobStatus.SUCCEEDED,
            ProviderJobStatus.FAILED,
            ProviderJobStatus.CANCELLED,
        }
    ),
    ProviderJobStatus.WAITING_PROVIDER: frozenset(
        {
            ProviderJobStatus.SUCCEEDED,
            ProviderJobStatus.FAILED,
            ProviderJobStatus.CANCELLED,
            ProviderJobStatus.EXPIRED,
        }
    ),
    ProviderJobStatus.SUCCEEDED: frozenset(),
    ProviderJobStatus.FAILED: frozenset(),
    ProviderJobStatus.CANCELLED: frozenset(),
    ProviderJobStatus.EXPIRED: frozenset(),
}


def ensure_transition_allowed(current: Enum, target: Enum, transitions: dict[Enum, frozenset[Enum]]) -> None:
    allowed_targets = transitions[current]
    if target not in allowed_targets:
        raise StateTransitionError(f"Invalid transition: {current.value} -> {target.value}")


def transition_workflow_run(current: WorkflowRunStatus, target: WorkflowRunStatus) -> WorkflowRunStatus:
    ensure_transition_allowed(current, target, WORKFLOW_RUN_TRANSITIONS)
    return target


def transition_node_run(current: NodeRunStatus, target: NodeRunStatus) -> NodeRunStatus:
    ensure_transition_allowed(current, target, NODE_RUN_TRANSITIONS)
    return target


def transition_provider_job(current: ProviderJobStatus, target: ProviderJobStatus) -> ProviderJobStatus:
    ensure_transition_allowed(current, target, PROVIDER_JOB_TRANSITIONS)
    return target

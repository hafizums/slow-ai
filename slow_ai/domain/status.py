"""Run, node, and provider job statuses."""

from __future__ import annotations

from enum import Enum


class WorkflowRunStatus(str, Enum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_PROVIDER = "WAITING_PROVIDER"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class NodeRunStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_PROVIDER = "WAITING_PROVIDER"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class ProviderJobStatus(str, Enum):
    QUEUED = "QUEUED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    WAITING_PROVIDER = "WAITING_PROVIDER"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


WORKFLOW_TERMINAL_STATUSES = frozenset(
    {
        WorkflowRunStatus.SUCCEEDED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.CANCELLED,
        WorkflowRunStatus.EXPIRED,
    }
)

NODE_TERMINAL_STATUSES = frozenset(
    {
        NodeRunStatus.SUCCEEDED,
        NodeRunStatus.FAILED,
        NodeRunStatus.SKIPPED,
        NodeRunStatus.CANCELLED,
    }
)

PROVIDER_JOB_TERMINAL_STATUSES = frozenset(
    {
        ProviderJobStatus.SUCCEEDED,
        ProviderJobStatus.FAILED,
        ProviderJobStatus.CANCELLED,
        ProviderJobStatus.EXPIRED,
    }
)

"""Pure domain rules and contracts for slow_ai."""

from slow_ai.domain.exceptions import (
    GraphValidationError,
    ProviderInvariantError,
    RegistryError,
    SlowAIError,
    StateTransitionError,
)
from slow_ai.domain.status import NodeRunStatus, ProviderJobStatus, WorkflowRunStatus
from slow_ai.domain.workflow_graph import WorkflowEdge, WorkflowGraph, WorkflowNode

__all__ = [
    "GraphValidationError",
    "NodeRunStatus",
    "ProviderInvariantError",
    "ProviderJobStatus",
    "RegistryError",
    "SlowAIError",
    "StateTransitionError",
    "WorkflowEdge",
    "WorkflowGraph",
    "WorkflowNode",
    "WorkflowRunStatus",
    "parse_workflow_json",
    "validate_workflow_json",
]


def __getattr__(name):
    if name in {"parse_workflow_json", "validate_workflow_json"}:
        from slow_ai.domain.workflow_json import parse_workflow_json, validate_workflow_json

        return {
            "parse_workflow_json": parse_workflow_json,
            "validate_workflow_json": validate_workflow_json,
        }[name]
    raise AttributeError(name)

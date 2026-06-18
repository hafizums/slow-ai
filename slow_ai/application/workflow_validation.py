"""Workflow validation application service."""

from __future__ import annotations

from typing import Any, Mapping

from slow_ai.domain.workflow_graph import WorkflowGraph
from slow_ai.domain.workflow_json import validate_workflow_json
from slow_ai.node_registry.registry import NodeRegistry


def validate_workflow(
    workflow_json: Mapping[str, Any] | str,
    node_registry: NodeRegistry | None = None,
) -> WorkflowGraph:
    return validate_workflow_json(workflow_json, node_registry=node_registry)

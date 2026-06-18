"""Node run worker entrypoint."""

from __future__ import annotations

import json
from typing import Any, Mapping

from slow_ai.engine.node_runner import NodeRunner
from slow_ai.infrastructure.repositories import FrappeEngineRepository
from slow_ai.node_registry.registry import NodeRegistry


def run_node(node_run_name: str, node_registry: NodeRegistry | None = None) -> None:
    """Execute one persisted node run with inputs from completed upstream nodes."""
    repository = FrappeEngineRepository()
    node_run = repository.get_node_run(node_run_name)
    graph = repository.get_workflow_graph_for_run(node_run.workflow_run)
    node = graph.node_by_id()[node_run.node_id]
    node_runs_by_node_id = repository.get_node_runs_by_node_id(node_run.workflow_run)
    inputs = _resolve_inputs(graph.incoming_edges(node.id), node_runs_by_node_id)
    NodeRunner(repository=repository, node_registry=node_registry).run_node(node_run.name, node, inputs)


def _resolve_inputs(edges, node_runs_by_node_id: Mapping[str, Any]) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    for edge in edges:
        source_node_run = node_runs_by_node_id[edge.source]
        source_outputs = _loads_json(source_node_run.output_json, {})
        if edge.source_port not in source_outputs:
            raise KeyError(f"Missing upstream output: {edge.source}.{edge.source_port}")
        inputs[edge.target_port] = source_outputs[edge.source_port]
    return inputs


def _loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)

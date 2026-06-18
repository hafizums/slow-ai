"""Workflow DAG executor."""

from __future__ import annotations

from typing import Any, Mapping

from slow_ai.domain.status import NODE_TERMINAL_STATUSES, WORKFLOW_TERMINAL_STATUSES, NodeRunStatus, WorkflowRunStatus
from slow_ai.engine.dag import topological_sort
from slow_ai.engine.node_runner import NodeRunner
from slow_ai.engine.state_machine import transition_node_run, transition_workflow_run
from slow_ai.infrastructure.repositories import FrappeEngineRepository
from slow_ai.node_registry.registry import NodeRegistry, create_default_registry


class WorkflowExecutor:
    def __init__(
        self,
        repository: FrappeEngineRepository | None = None,
        node_registry: NodeRegistry | None = None,
    ) -> None:
        self.repository = repository or FrappeEngineRepository()
        self.node_registry = node_registry or create_default_registry()
        self.node_runner = NodeRunner(self.repository, self.node_registry)

    def run(self, workflow_run_name: str) -> None:
        workflow_run = self.repository.get_workflow_run(workflow_run_name)
        current_workflow_status = WorkflowRunStatus(workflow_run.status)
        if current_workflow_status in WORKFLOW_TERMINAL_STATUSES:
            return
        if current_workflow_status == WorkflowRunStatus.RUNNING:
            running_status = current_workflow_status
        else:
            running_status = transition_workflow_run(current_workflow_status, WorkflowRunStatus.RUNNING)
            self.repository.set_workflow_status(workflow_run.name, running_status)

        outputs_by_node: dict[str, Mapping[str, Any]] = {}
        graph = self.repository.get_workflow_graph_for_run(workflow_run.name)
        node_runs_by_node_id = self.repository.get_node_runs_by_node_id(workflow_run.name)
        for node_id, node_run in node_runs_by_node_id.items():
            if NodeRunStatus(node_run.status) == NodeRunStatus.SUCCEEDED:
                outputs_by_node[node_id] = _loads_json(node_run.output_json, {})

        try:
            for node_id in topological_sort(graph):
                node = graph.node_by_id()[node_id]
                node_run = node_runs_by_node_id[node_id]
                node_status = NodeRunStatus(node_run.status)
                if node_status == NodeRunStatus.SUCCEEDED:
                    continue
                if node_status in NODE_TERMINAL_STATUSES:
                    raise RuntimeError(f"Cannot resume terminal node run: {node_run.name} {node_status.value}")
                try:
                    inputs = _resolve_inputs(graph.incoming_edges(node_id), outputs_by_node)
                except Exception as exc:
                    failed_node_status = transition_node_run(
                        NodeRunStatus(node_run.status), NodeRunStatus.FAILED
                    )
                    self.repository.set_node_status(
                        node_run.name,
                        failed_node_status,
                        error=_error_payload(exc),
                    )
                    raise
                result = self.node_runner.run_node(node_run.name, node, inputs)
                outputs_by_node[node_id] = result.outputs
                if result.waiting_provider:
                    waiting_status = transition_workflow_run(
                        WorkflowRunStatus.RUNNING,
                        WorkflowRunStatus.WAITING_PROVIDER,
                    )
                    self.repository.set_workflow_status(workflow_run.name, waiting_status)
                    return

            succeeded_status = transition_workflow_run(
                WorkflowRunStatus.RUNNING, WorkflowRunStatus.SUCCEEDED
            )
            self.repository.set_workflow_status(workflow_run.name, succeeded_status)
        except Exception as exc:
            failed_status = transition_workflow_run(WorkflowRunStatus.RUNNING, WorkflowRunStatus.FAILED)
            self.repository.set_workflow_status(
                workflow_run.name,
                failed_status,
                _error_payload(exc),
            )
            raise


def run_workflow(workflow_run_name: str) -> None:
    WorkflowExecutor().run(workflow_run_name)


def _resolve_inputs(edges, outputs_by_node: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    for edge in edges:
        source_outputs = outputs_by_node.get(edge.source, {})
        if edge.source_port not in source_outputs:
            raise KeyError(f"Missing upstream output: {edge.source}.{edge.source_port}")
        inputs[edge.target_port] = source_outputs[edge.source_port]
    return inputs


def _error_payload(exc: Exception) -> dict[str, str]:
    return {"type": exc.__class__.__name__, "message": str(exc)}


def _loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    import json

    return json.loads(value)

"""Single-node execution through NodeDefinition contracts."""

from __future__ import annotations

from typing import Any, Mapping

from slow_ai.domain.status import NodeRunStatus
from slow_ai.domain.workflow_graph import WorkflowNode
from slow_ai.engine.state_machine import transition_node_run
from slow_ai.infrastructure.repositories import FrappeEngineRepository
from slow_ai.node_registry.contracts import ExecutionContext, NodeExecutionResult
from slow_ai.node_registry.registry import NodeRegistry, create_default_registry


class NodeRunner:
    def __init__(
        self,
        repository: FrappeEngineRepository | None = None,
        node_registry: NodeRegistry | None = None,
    ) -> None:
        self.repository = repository or FrappeEngineRepository()
        self.node_registry = node_registry or create_default_registry()

    def run_node(
        self,
        node_run_name: str,
        node: WorkflowNode,
        inputs: Mapping[str, Any],
    ) -> NodeExecutionResult:
        node_run = self.repository.get_node_run(node_run_name)
        workflow_run = self.repository.get_workflow_run(node_run.workflow_run)

        definition = self.node_registry.get(node.type)
        runtime_inputs = _merge_configured_inputs(definition.input_schema(), node.config, inputs)
        current_status = NodeRunStatus(node_run.status)
        if current_status == NodeRunStatus.PENDING:
            ready_status = transition_node_run(current_status, NodeRunStatus.READY)
            self.repository.set_node_status(node_run.name, ready_status, inputs=runtime_inputs)
            running_status = transition_node_run(ready_status, NodeRunStatus.RUNNING)
        else:
            running_status = transition_node_run(current_status, NodeRunStatus.RUNNING)
            self.repository.set_node_status(node_run.name, running_status, inputs=runtime_inputs)
        self.repository.set_node_status(node_run.name, running_status)

        try:
            definition.validate_inputs(runtime_inputs)
            definition.validate_config(node.config)
            result = definition.execute(
                ExecutionContext(
                    workflow_run_name=node_run.workflow_run,
                    node_run_name=node_run.name,
                    project_name=workflow_run.project,
                ),
                runtime_inputs,
                node.config,
            )
            if result.waiting_provider:
                waiting_status = transition_node_run(running_status, NodeRunStatus.WAITING_PROVIDER)
                self.repository.set_node_status(
                    node_run.name,
                    waiting_status,
                    outputs=result.outputs,
                    cost_usd=result.cost_usd,
                    provider_job_name=result.provider_job_name,
                )
                return result
            succeeded_status = transition_node_run(running_status, NodeRunStatus.SUCCEEDED)
            self.repository.set_node_status(
                node_run.name,
                succeeded_status,
                outputs=result.outputs,
                cost_usd=result.cost_usd,
                provider_job_name=result.provider_job_name,
            )
            return result
        except Exception as exc:
            failed_status = transition_node_run(running_status, NodeRunStatus.FAILED)
            self.repository.set_node_status(
                node_run.name,
                failed_status,
                error={"type": exc.__class__.__name__, "message": str(exc)},
            )
            raise


def _merge_configured_inputs(
    input_schema: Mapping[str, Any],
    config: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    runtime_inputs = dict(inputs)
    for port_name in input_schema:
        if port_name not in runtime_inputs and port_name in config:
            runtime_inputs[port_name] = config[port_name]
    return runtime_inputs

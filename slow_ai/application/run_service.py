"""Application service for creating workflow runs from editable drafts."""

from __future__ import annotations

from dataclasses import dataclass

from slow_ai.application.contracts import NodeRunRepository, WorkflowRunRepository, WorkflowVersionRepository
from slow_ai.application.run_preflight import RunPreflightService
from slow_ai.application.workflow_validation import validate_workflow
from slow_ai.infrastructure.queue import FrappeWorkflowQueue
from slow_ai.infrastructure.repositories import (
    FrappeNodeRunRepository,
    FrappeWorkflowDraftRepository,
    FrappeWorkflowRunRepository,
    FrappeWorkflowVersionRepository,
)
from slow_ai.node_registry.registry import NodeRegistry


@dataclass(frozen=True)
class StartRunResult:
    workflow_version: str
    workflow_run: str
    node_runs: tuple[str, ...]
    queue_job_id: str | None = None


class RunService:
    def __init__(
        self,
        draft_repository: FrappeWorkflowDraftRepository | None = None,
        version_repository: WorkflowVersionRepository | None = None,
        run_repository: WorkflowRunRepository | None = None,
        node_run_repository: NodeRunRepository | None = None,
        node_registry: NodeRegistry | None = None,
        workflow_queue: FrappeWorkflowQueue | None = None,
        run_preflight: RunPreflightService | None = None,
    ) -> None:
        self.draft_repository = draft_repository or FrappeWorkflowDraftRepository()
        self.version_repository = version_repository or FrappeWorkflowVersionRepository()
        self.run_repository = run_repository or FrappeWorkflowRunRepository()
        self.node_run_repository = node_run_repository or FrappeNodeRunRepository()
        self.node_registry = node_registry
        self.workflow_queue = workflow_queue or FrappeWorkflowQueue()
        self.run_preflight = run_preflight or RunPreflightService()

    def start_run(self, workflow_name: str) -> StartRunResult:
        draft = self.draft_repository.get_draft(workflow_name)
        graph = validate_workflow(draft.as_workflow_json(), node_registry=self.node_registry)
        self.run_preflight.assert_can_start(draft, graph)
        workflow_version = self.version_repository.create_immutable_version(draft, graph)
        workflow_run = self.run_repository.create_workflow_run(workflow_version)
        node_runs = self.node_run_repository.create_node_runs(workflow_run, graph)
        queue_job_id = self.workflow_queue.enqueue_workflow_run(workflow_run)
        return StartRunResult(
            workflow_version=workflow_version,
            workflow_run=workflow_run,
            node_runs=node_runs,
            queue_job_id=queue_job_id,
        )


def start_run(workflow_name: str) -> StartRunResult:
    return RunService().start_run(workflow_name)

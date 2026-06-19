"""Application service for creating workflow runs from editable drafts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from slow_ai.application.contracts import (
    NodeRunRepository,
    WorkflowDraft,
    WorkflowRunRepository,
    WorkflowVersionRepository,
)
from slow_ai.application.project_access import assert_can_run_project
from slow_ai.application.run_preflight import RunPreflightService
from slow_ai.application.workflow_validation import validate_workflow
from slow_ai.domain.snapshots import canonical_json
from slow_ai.domain.status import WorkflowRunStatus
from slow_ai.infrastructure.queue import FrappeWorkflowQueue
from slow_ai.infrastructure.repositories import (
    FrappeNodeRunRepository,
    FrappeWorkflowDraftRepository,
    FrappeWorkflowRunRepository,
    FrappeWorkflowVersionRepository,
)
from slow_ai.node_registry.registry import NodeRegistry

RUN_START_IDEMPOTENCY_WINDOW_SECONDS = 30
RUN_START_IDEMPOTENT_STATUSES = frozenset(
    {
        WorkflowRunStatus.QUEUED.value,
        WorkflowRunStatus.RUNNING.value,
        WorkflowRunStatus.WAITING_PROVIDER.value,
    }
)


@dataclass(frozen=True)
class StartRunResult:
    workflow_version: str
    workflow_run: str
    node_runs: tuple[str, ...]
    queue_job_id: str | None = None


@dataclass(frozen=True)
class _RecentActiveRun:
    workflow_version: str
    workflow_run: str
    status: str
    node_runs: tuple[str, ...]


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
        assert_can_run_project(draft.project)
        graph = validate_workflow(draft.as_workflow_json(), node_registry=self.node_registry)
        self.run_preflight.assert_can_start(draft, graph)
        existing = self._find_recent_equivalent_active_run(draft, graph)
        if existing:
            queue_job_id = None
            if existing.status == WorkflowRunStatus.QUEUED.value:
                queue_job_id = self.workflow_queue.enqueue_workflow_run(existing.workflow_run)
            return StartRunResult(
                workflow_version=existing.workflow_version,
                workflow_run=existing.workflow_run,
                node_runs=existing.node_runs,
                queue_job_id=queue_job_id,
            )
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

    def _find_recent_equivalent_active_run(self, draft: WorkflowDraft, graph) -> _RecentActiveRun | None:
        window_start = now_datetime() - timedelta(seconds=RUN_START_IDEMPOTENCY_WINDOW_SECONDS)
        versions = frappe.get_all(
            "AI Workflow Version",
            filters={"workflow": draft.name, "creation": [">=", window_start]},
            fields=[
                "name",
                "nodes_json",
                "edges_json",
                "layout_json",
                "source_template",
                "source_template_version",
            ],
            order_by="creation desc",
            limit=10,
        )
        expected_nodes = canonical_json(list(draft.nodes))
        expected_edges = canonical_json(list(draft.edges))
        expected_layout = canonical_json(draft.layout)
        for version in versions:
            if version.nodes_json != expected_nodes:
                continue
            if version.edges_json != expected_edges:
                continue
            if version.layout_json != expected_layout:
                continue
            if (version.source_template or None) != (draft.source_template or None):
                continue
            if (version.source_template_version or None) != (draft.source_template_version or None):
                continue
            workflow_run = frappe.get_all(
                "AI Workflow Run",
                filters={
                    "workflow_version": version.name,
                    "status": ["in", sorted(RUN_START_IDEMPOTENT_STATUSES)],
                },
                fields=["name", "status"],
                order_by="creation desc",
                limit=1,
            )
            if not workflow_run:
                continue
            node_runs = tuple(
                frappe.get_all(
                    "AI Node Run",
                    filters={"workflow_run": workflow_run[0].name},
                    pluck="name",
                    order_by="creation asc",
                )
            )
            if len(node_runs) != len(graph.node_by_id()):
                node_runs = self.node_run_repository.create_node_runs(workflow_run[0].name, graph)
            return _RecentActiveRun(
                workflow_version=version.name,
                workflow_run=workflow_run[0].name,
                status=workflow_run[0].status,
                node_runs=node_runs,
            )
        return None


def start_run(workflow_name: str) -> StartRunResult:
    return RunService().start_run(workflow_name)

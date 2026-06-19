"""Application-layer repository contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from slow_ai.domain.workflow_graph import WorkflowGraph


@dataclass(frozen=True)
class WorkflowDraft:
    name: str
    project: str
    nodes: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]
    layout: Mapping[str, Any]
    source_template: str | None = None
    source_template_version: str | None = None

    def as_workflow_json(self) -> dict[str, Any]:
        return {"nodes": list(self.nodes), "edges": list(self.edges)}


class WorkflowVersionRepository(Protocol):
    def create_immutable_version(self, draft: WorkflowDraft, graph: WorkflowGraph) -> str:
        """Persist an immutable AI Workflow Version and return its document name."""


class WorkflowRunRepository(Protocol):
    def create_workflow_run(self, workflow_version_name: str) -> str:
        """Persist an AI Workflow Run for an immutable workflow version."""


class NodeRunRepository(Protocol):
    def create_node_runs(self, workflow_run_name: str, graph: WorkflowGraph) -> tuple[str, ...]:
        """Persist AI Node Run records for all nodes in the version graph."""

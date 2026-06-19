"""Frappe repository adapters for workflow run persistence."""

from __future__ import annotations

import json
from typing import Any, Mapping

import frappe
from frappe.utils import now_datetime

from slow_ai.application.contracts import WorkflowDraft
from slow_ai.domain.snapshots import canonical_json, snapshot_hash
from slow_ai.domain.status import NodeRunStatus, WorkflowRunStatus
from slow_ai.domain.workflow_graph import WorkflowGraph
from slow_ai.engine.dag import topological_sort
from slow_ai.infrastructure.realtime import publish_node_run_update, publish_workflow_run_update


class FrappeWorkflowDraftRepository:
    def get_draft(self, workflow_name: str) -> WorkflowDraft:
        workflow = frappe.get_doc("AI Workflow", workflow_name)
        nodes = _loads_json(workflow.draft_nodes_json, [])
        edges = _loads_json(workflow.draft_edges_json, [])
        layout = _loads_json(workflow.layout_json, {})
        return WorkflowDraft(
            name=workflow.name,
            project=workflow.project,
            nodes=tuple(nodes),
            edges=tuple(edges),
            layout=layout,
            source_template=getattr(workflow, "source_template", None),
            source_template_version=getattr(workflow, "source_template_version", None),
        )


class FrappeWorkflowVersionRepository:
    def create_immutable_version(self, draft: WorkflowDraft, graph: WorkflowGraph) -> str:
        version_no = self._next_version_no(draft.name)
        snapshot = {
            "workflow": draft.name,
            "version_no": version_no,
            "nodes": [node for node in draft.nodes],
            "edges": [edge for edge in draft.edges],
            "layout": draft.layout,
            "source_template": draft.source_template,
            "source_template_version": draft.source_template_version,
        }
        values = {
            "doctype": "AI Workflow Version",
            "workflow": draft.name,
            "version_no": version_no,
            "snapshot_hash": snapshot_hash(snapshot),
            "created_by": frappe.session.user,
            "created_at": now_datetime(),
            "source_template": draft.source_template,
            "source_template_version": draft.source_template_version,
            "nodes_json": canonical_json([node for node in draft.nodes]),
            "edges_json": canonical_json([edge for edge in draft.edges]),
            "layout_json": canonical_json(draft.layout),
        }
        version = frappe.get_doc(values).insert(ignore_permissions=True)
        frappe.db.set_value("AI Workflow", draft.name, "current_version", version.name)
        return version.name

    def _next_version_no(self, workflow_name: str) -> int:
        latest = frappe.get_all(
            "AI Workflow Version",
            filters={"workflow": workflow_name},
            fields=["version_no"],
            order_by="version_no desc",
            limit=1,
        )
        if not latest:
            return 1
        return int(latest[0].version_no or 0) + 1


class FrappeWorkflowRunRepository:
    def create_workflow_run(self, workflow_version_name: str) -> str:
        version = frappe.get_doc("AI Workflow Version", workflow_version_name)
        workflow = frappe.get_doc("AI Workflow", version.workflow)
        workflow_run = frappe.get_doc(
            {
                "doctype": "AI Workflow Run",
                "project": workflow.project,
                "workflow": workflow.name,
                "workflow_version": version.name,
                "source_template": getattr(version, "source_template", None),
                "source_template_version": getattr(version, "source_template_version", None),
                "status": WorkflowRunStatus.QUEUED.value,
                "queued_at": now_datetime(),
            }
        ).insert(ignore_permissions=True)
        return workflow_run.name


class FrappeNodeRunRepository:
    def create_node_runs(self, workflow_run_name: str, graph: WorkflowGraph) -> tuple[str, ...]:
        nodes = graph.node_by_id()
        existing_rows = frappe.get_all(
            "AI Node Run",
            filters={"workflow_run": workflow_run_name},
            fields=["name", "node_id"],
            order_by="creation asc",
        )
        existing_by_node_id = {row.node_id: row.name for row in existing_rows}
        node_run_names: list[str] = []
        for node_id in topological_sort(graph):
            if node_id in existing_by_node_id:
                node_run_names.append(existing_by_node_id[node_id])
                continue
            node = nodes[node_id]
            node_run = frappe.get_doc(
                {
                    "doctype": "AI Node Run",
                    "workflow_run": workflow_run_name,
                    "node_id": node.id,
                    "node_type": node.type,
                    "status": NodeRunStatus.PENDING.value,
                    "attempt_no": 1,
                    "input_json": "{}",
                    "config_json": canonical_json(node.config),
                    "config_hash": snapshot_hash({"config": node.config}),
                }
            ).insert(ignore_permissions=True)
            node_run_names.append(node_run.name)
        return tuple(node_run_names)


class FrappeEngineRepository:
    def get_workflow_run(self, workflow_run_name: str):
        return frappe.get_doc("AI Workflow Run", workflow_run_name)

    def get_node_run(self, node_run_name: str):
        return frappe.get_doc("AI Node Run", node_run_name)

    def get_workflow_version(self, workflow_version_name: str):
        return frappe.get_doc("AI Workflow Version", workflow_version_name)

    def get_workflow_graph_for_run(self, workflow_run_name: str) -> WorkflowGraph:
        workflow_run = self.get_workflow_run(workflow_run_name)
        version = self.get_workflow_version(workflow_run.workflow_version)
        return WorkflowGraph.from_dict(
            {
                "nodes": _loads_json(version.nodes_json, []),
                "edges": _loads_json(version.edges_json, []),
            }
        )

    def get_node_runs_by_node_id(self, workflow_run_name: str) -> dict[str, Any]:
        node_runs = frappe.get_all(
            "AI Node Run",
            filters={"workflow_run": workflow_run_name},
            fields=["name", "node_id"],
            order_by="creation asc",
        )
        return {row.node_id: frappe.get_doc("AI Node Run", row.name) for row in node_runs}

    def set_workflow_status(
        self,
        workflow_run_name: str,
        status: WorkflowRunStatus,
        error: Mapping[str, Any] | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status.value}
        if status == WorkflowRunStatus.RUNNING:
            values["started_at"] = now_datetime()
        if status in {
            WorkflowRunStatus.SUCCEEDED,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.CANCELLED,
            WorkflowRunStatus.EXPIRED,
        }:
            values["completed_at"] = now_datetime()
        if error is not None:
            values["error_json"] = canonical_json(error)
        frappe.db.set_value("AI Workflow Run", workflow_run_name, values)
        publish_workflow_run_update(
            workflow_run_name,
            status.value,
            {"error": error} if error is not None else None,
        )

    def set_node_status(
        self,
        node_run_name: str,
        status: NodeRunStatus,
        *,
        inputs: Mapping[str, Any] | None = None,
        outputs: Mapping[str, Any] | None = None,
        error: Mapping[str, Any] | None = None,
        cost_usd: float | None = None,
        provider_job_name: str | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status.value}
        if status == NodeRunStatus.RUNNING:
            values["started_at"] = now_datetime()
        if status in {
            NodeRunStatus.SUCCEEDED,
            NodeRunStatus.FAILED,
            NodeRunStatus.SKIPPED,
            NodeRunStatus.CANCELLED,
        }:
            values["completed_at"] = now_datetime()
        if inputs is not None:
            values["input_json"] = canonical_json(inputs)
            values["input_hash"] = snapshot_hash({"inputs": inputs})
        if outputs is not None:
            values["output_json"] = canonical_json(outputs)
        if error is not None:
            values["error_json"] = canonical_json(error)
        if cost_usd is not None:
            values["cost_usd"] = cost_usd
        if provider_job_name is not None:
            values["provider_job"] = provider_job_name
        frappe.db.set_value("AI Node Run", node_run_name, values)
        node_run = self.get_node_run(node_run_name)
        extra: dict[str, Any] = {}
        if outputs is not None:
            extra["outputs"] = outputs
        if error is not None:
            extra["error"] = error
        if provider_job_name is not None:
            extra["provider_job"] = provider_job_name
        publish_node_run_update(node_run_name, node_run.workflow_run, status.value, extra or None)


def _loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)

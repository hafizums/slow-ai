import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.run_service import RunService
from slow_ai.domain.exceptions import GraphValidationError
from slow_ai.domain.workflow_graph import WorkflowNode
from slow_ai.engine.executor import WorkflowExecutor
from slow_ai.engine.node_runner import NodeRunner


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Engine Project"),
            "status": "Open",
        }
    )


def create_workflow(project, nodes, edges):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Engine Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(nodes),
            "draft_edges_json": json.dumps(edges),
            "layout_json": json.dumps({"nodes": []}),
        }
    )


def text_workflow(project):
    return create_workflow(
        project,
        [
            {
                "id": "prompt_1",
                "type": "text_prompt",
                "config": {"text": "A cinematic product shot"},
            },
            {"id": "output_1", "type": "export_output", "config": {}},
        ],
        [
            {
                "id": "edge_1",
                "source": "prompt_1",
                "source_port": "text",
                "target": "output_1",
                "target_port": "text",
            }
        ],
    )


class TestEngineCore(FrappeTestCase):
    def test_start_run_creates_immutable_workflow_version_and_node_runs(self):
        workflow = text_workflow(create_project())

        result = RunService().start_run(workflow.name)

        version = frappe.get_doc("AI Workflow Version", result.workflow_version)
        workflow_run = frappe.get_doc("AI Workflow Run", result.workflow_run)
        node_runs = frappe.get_all(
            "AI Node Run",
            filters={"workflow_run": workflow_run.name},
            fields=["node_id", "node_type", "status"],
            order_by="creation asc",
        )

        self.assertEqual(version.workflow, workflow.name)
        self.assertEqual(version.version_no, 1)
        self.assertEqual(workflow_run.workflow_version, version.name)
        self.assertEqual(workflow_run.status, "QUEUED")
        self.assertEqual(len(node_runs), 2)
        self.assertEqual([row.node_id for row in node_runs], ["prompt_1", "output_1"])
        self.assertEqual({row.status for row in node_runs}, {"PENDING"})
        self.assertEqual(frappe.db.get_value("AI Workflow", workflow.name, "current_version"), version.name)

        version.snapshot_hash = unique("changed")
        with self.assertRaises(frappe.ValidationError):
            version.save(ignore_permissions=True)

    def test_dag_runner_executes_nodes_and_persists_outputs(self):
        result = RunService().start_run(text_workflow(create_project()).name)

        WorkflowExecutor().run(result.workflow_run)

        workflow_run = frappe.get_doc("AI Workflow Run", result.workflow_run)
        node_runs = frappe.get_all(
            "AI Node Run",
            filters={"workflow_run": result.workflow_run},
            fields=["node_id", "status", "input_json", "output_json", "error_json"],
            order_by="creation asc",
        )
        output_node = next(row for row in node_runs if row.node_id == "output_1")

        self.assertEqual(workflow_run.status, "SUCCEEDED")
        self.assertEqual({row.status for row in node_runs}, {"SUCCEEDED"})
        self.assertEqual(json.loads(output_node.input_json), {"text": "A cinematic product shot"})
        self.assertEqual(json.loads(output_node.output_json), {"text": "A cinematic product shot"})
        self.assertFalse(output_node.error_json)

    def test_dag_runner_persists_failure_state(self):
        workflow = create_workflow(
            create_project(),
            [
                {
                    "id": "upload_1",
                    "type": "upload_asset",
                    "config": {"asset": "AI-ASSET-DOES-NOT-READ-FILE", "asset_type": "IMAGE"},
                },
                {"id": "output_1", "type": "export_output", "config": {}},
            ],
            [
                {
                    "id": "edge_1",
                    "source": "upload_1",
                    "source_port": "video",
                    "target": "output_1",
                    "target_port": "video",
                }
            ],
        )
        result = RunService().start_run(workflow.name)

        with self.assertRaises(KeyError):
            WorkflowExecutor().run(result.workflow_run)

        workflow_run = frappe.get_doc("AI Workflow Run", result.workflow_run)
        node_runs = frappe.get_all(
            "AI Node Run",
            filters={"workflow_run": result.workflow_run},
            fields=["node_id", "status", "output_json", "error_json"],
            order_by="creation asc",
        )
        upload_node = next(row for row in node_runs if row.node_id == "upload_1")
        output_node = next(row for row in node_runs if row.node_id == "output_1")

        self.assertEqual(workflow_run.status, "FAILED")
        self.assertIn("Missing upstream output", workflow_run.error_json)
        self.assertEqual(upload_node.status, "SUCCEEDED")
        self.assertEqual(json.loads(upload_node.output_json), {"image": "AI-ASSET-DOES-NOT-READ-FILE"})
        self.assertEqual(output_node.status, "FAILED")
        self.assertIn("Missing upstream output", output_node.error_json)
        self.assertFalse(output_node.output_json)

    def test_node_runner_persists_node_failure_state(self):
        result = RunService().start_run(text_workflow(create_project()).name)
        output_node_run_name = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": result.workflow_run, "node_id": "output_1"},
            "name",
        )

        with self.assertRaises(GraphValidationError):
            NodeRunner().run_node(
                output_node_run_name,
                WorkflowNode(id="output_1", type="export_output", config={}),
                inputs={},
            )

        output_node_run = frappe.get_doc("AI Node Run", output_node_run_name)
        self.assertEqual(output_node_run.status, "FAILED")
        self.assertIn("export_output requires at least one connected input", output_node_run.error_json)

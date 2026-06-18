import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.run_service import RunService
from slow_ai.engine.executor import WorkflowExecutor


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Tool Mode Project"),
            "status": "Open",
        }
    )


def tool_nodes(text: str = "Tool mode answer"):
    return [
        {"id": "prompt_1", "type": "text_prompt", "config": {"text": text}},
        {
            "id": "tool_output_1",
            "type": "tool_output",
            "config": {
                "output_name": "answer",
                "description": "Primary tool response",
                "schema": {"type": "string"},
            },
        },
    ]


def tool_edges():
    return [
        {
            "id": "edge_1",
            "source": "prompt_1",
            "source_port": "text",
            "target": "tool_output_1",
            "target_port": "text",
        }
    ]


class TestToolModeDesign(FrappeTestCase):
    def test_tool_output_node_executes_as_persisted_output_node(self):
        project = create_project()
        workflow = insert_doc(
            {
                "doctype": "AI Workflow",
                "title": unique("Tool Mode Workflow"),
                "project": project.name,
                "status": "DRAFT",
                "draft_nodes_json": json.dumps(tool_nodes()),
                "draft_edges_json": json.dumps(tool_edges()),
                "layout_json": json.dumps({"nodes": []}),
            }
        )
        result = RunService().start_run(workflow.name)

        WorkflowExecutor().run(result.workflow_run)

        workflow_run = frappe.get_doc("AI Workflow Run", result.workflow_run)
        tool_node_run = frappe.get_doc(
            "AI Node Run",
            frappe.db.get_value(
                "AI Node Run",
                {"workflow_run": result.workflow_run, "node_id": "tool_output_1"},
                "name",
            ),
        )
        output = json.loads(tool_node_run.output_json)

        self.assertEqual(workflow_run.status, "SUCCEEDED")
        self.assertEqual(tool_node_run.status, "SUCCEEDED")
        self.assertEqual(output["output_name"], "answer")
        self.assertEqual(output["values"]["text"], "Tool mode answer")
        self.assertEqual(output["schema"], {"type": "string"})

    def test_template_api_saves_lists_gets_and_instantiates_real_workflow(self):
        project = create_project()
        template = frappe.call(
            "slow_ai.api.templates.save_template",
            template_name=unique("Tool Template"),
            status="PUBLISHED",
            category="Tool",
            description="Template API integration test",
            nodes=json.dumps(tool_nodes("From template")),
            edges=json.dumps(tool_edges()),
            layout=json.dumps({"nodes": [{"id": "prompt_1", "x": 10, "y": 20}]}),
        )
        listed = frappe.call("slow_ai.api.templates.list_templates", status="PUBLISHED", category="Tool")
        loaded = frappe.call("slow_ai.api.templates.get_template", template=template["name"])
        workflow = frappe.call(
            "slow_ai.api.templates.create_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Workflow From Tool Template",
        )
        run = frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])

        self.assertTrue(frappe.db.exists("AI Workflow Template", template["name"]))
        self.assertIn(template["name"], {row["name"] for row in listed["templates"]})
        self.assertEqual(loaded["nodes"][1]["type"], "tool_output")
        self.assertEqual(workflow["title"], "Workflow From Tool Template")
        self.assertEqual(workflow["project"], project.name)
        self.assertEqual(workflow["nodes"][1]["config"]["output_name"], "answer")
        self.assertTrue(frappe.db.exists("AI Workflow Version", run["workflow_version"]))
        self.assertTrue(frappe.db.exists("AI Workflow Run", run["workflow_run"]))

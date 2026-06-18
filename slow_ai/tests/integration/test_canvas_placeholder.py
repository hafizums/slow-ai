import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase


ALLOWED_CANVAS_METHODS = {
    "slow_ai.api.nodes.get_object_info",
    "slow_ai.api.workflows.get_workflow",
    "slow_ai.api.workflows.save_workflow",
    "slow_ai.api.runs.start_run",
    "slow_ai.api.runs.get_run_status",
    "slow_ai.api.runs.get_history",
    "slow_ai.api.queue.get_queue_status",
}

FORBIDDEN_CANVAS_FRAGMENTS = (
    "ProviderAdapter",
    "ProviderRegistry",
    "WAVESPEED_API_KEY",
    "api_key_secret",
    "Authorization: Bearer",
    "WorkflowExecutor",
    "run_workflow",
    "checkpoint",
    "KSampler",
    "CUDA",
    "local model",
)


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def create_project():
    return frappe.get_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Canvas Project"),
            "status": "Open",
        }
    ).insert(ignore_permissions=True)


def canvas_nodes():
    return [
        {
            "id": "prompt_1",
            "type": "text_prompt",
            "label": "Prompt",
            "position": {"x": 96, "y": 128},
            "config": {"text": "Canvas placeholder prompt"},
        },
        {
            "id": "output_1",
            "type": "export_output",
            "label": "Output",
            "position": {"x": 416, "y": 128},
            "config": {},
        },
    ]


def canvas_edges():
    return [
        {
            "id": "edge_1",
            "source": "prompt_1",
            "source_port": "text",
            "target": "output_1",
            "target_port": "text",
        }
    ]


class TestCanvasPlaceholder(FrappeTestCase):
    def test_canvas_page_loads_only_api_driven_assets(self):
        frappe.reload_doc("slow_ai", "page", "slow_ai_canvas")
        page = frappe.get_doc("Page", "slow-ai-canvas")
        page.load_assets()

        self.assertEqual(page.module, "Slow Ai")
        self.assertIn("frappe.pages[\"slow-ai-canvas\"]", page.script)
        self.assertIn("frappe.templates[\"slow_ai_canvas\"]", page.script)
        self.assertIn("slow-ai-canvas__stage", page.style)
        for method in ALLOWED_CANVAS_METHODS:
            self.assertIn(method, page.script)
        for fragment in FORBIDDEN_CANVAS_FRAGMENTS:
            self.assertNotIn(fragment, page.script)

    def test_canvas_api_flow_saves_starts_and_reads_real_run_records(self):
        project = create_project()
        object_info = frappe.call("slow_ai.api.nodes.get_object_info")
        self.assertIn("text_prompt", object_info["nodes"])

        saved = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            project=project.name,
            title="Canvas Placeholder Workflow",
            nodes=json.dumps(canvas_nodes()),
            edges=json.dumps(canvas_edges()),
            layout=json.dumps({"nodes": [{"id": "prompt_1", "x": 96, "y": 128}]}),
        )
        loaded = frappe.call("slow_ai.api.workflows.get_workflow", workflow=saved["name"])
        run = frappe.call("slow_ai.api.runs.start_run", workflow=saved["name"])
        status = frappe.call("slow_ai.api.runs.get_run_status", workflow_run=run["workflow_run"])
        history = frappe.call("slow_ai.api.runs.get_history", workflow_run=run["workflow_run"])
        queue = frappe.call("slow_ai.api.queue.get_queue_status")

        self.assertEqual(loaded["name"], saved["name"])
        self.assertEqual(loaded["nodes"][0]["type"], "text_prompt")
        self.assertTrue(frappe.db.exists("AI Workflow Version", run["workflow_version"]))
        self.assertTrue(frappe.db.exists("AI Workflow Run", run["workflow_run"]))
        self.assertEqual(status["status"], "QUEUED")
        self.assertEqual(len(status["node_runs"]), 2)
        self.assertEqual(history["run"]["workflow_run"], run["workflow_run"])
        self.assertIn(run["workflow_run"], {row["name"] for row in queue["queued"]})

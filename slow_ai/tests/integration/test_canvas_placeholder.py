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
    "slow_ai.api.assets.view",
    "slow_ai.api.models.get_model_metadata",
}

FORBIDDEN_CANVAS_FRAGMENTS = (
    "ProviderAdapter",
    "ProviderRegistry",
    "WAVESPEED_API_KEY",
    "api_key_secret",
    "Authorization: Bearer",
    "api.wavespeed.ai",
    "wavespeed.ai/api",
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


def ensure_canvas_provider_catalog():
    if frappe.db.exists("AI Model", "wavespeed-ai/flux-dev"):
        model = frappe.get_doc("AI Model", "wavespeed-ai/flux-dev")
        model.status = "ENABLED"
        model.provider = "wavespeed"
        model.modality = "TEXT_TO_IMAGE"
        model.pricing_json = json.dumps({"unit": "run", "amount_usd": "0.012"})
        model.save(ignore_permissions=True)
    else:
        frappe.get_doc(
            {
                "doctype": "AI Model",
                "model_id": "wavespeed-ai/flux-dev",
                "model_name": "Canvas Placeholder Flux Dev",
                "provider": "wavespeed",
                "status": "ENABLED",
                "modality": "TEXT_TO_IMAGE",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": "0.012"}),
            }
        ).insert(ignore_permissions=True)
    frappe.get_doc(
        {
            "doctype": "AI Provider Account",
            "provider": "wavespeed",
            "account_label": unique("Canvas Provider"),
            "api_key_secret": "canvas-test-key",
            "is_default": 1,
            "status": "ACTIVE",
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
            "id": "image_1",
            "type": "provider_text_to_image",
            "label": "Provider Text to Image",
            "position": {"x": 376, "y": 128},
            "config": {
                "provider": "wavespeed",
                "model": "wavespeed-ai/flux-dev",
                "parameters": {
                    "size": "1024*1024",
                    "num_images": 1,
                    "enable_base64_output": False,
                },
            },
        },
        {
            "id": "output_1",
            "type": "export_output",
            "label": "Output",
            "position": {"x": 656, "y": 128},
            "config": {},
        },
    ]


def canvas_edges():
    return [
        {
            "id": "edge_1",
            "source": "prompt_1",
            "source_port": "text",
            "target": "image_1",
            "target_port": "prompt",
        },
        {
            "id": "edge_2",
            "source": "image_1",
            "source_port": "image",
            "target": "output_1",
            "target_port": "image",
        },
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
        self.assertIn("slow-ai-canvas__asset-output", page.style)
        self.assertIn("Provider Text to Image", page.script)
        self.assertIn("This workflow may call an external provider and spend credits.", page.script)
        self.assertIn("cost unknown", page.script)
        self.assertIn("frappe.confirm", page.script)
        for method in ALLOWED_CANVAS_METHODS:
            self.assertIn(method, page.script)
        for fragment in FORBIDDEN_CANVAS_FRAGMENTS:
            self.assertNotIn(fragment, page.script)

    def test_canvas_api_flow_saves_starts_and_reads_real_run_records(self):
        ensure_canvas_provider_catalog()
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
        self.assertEqual(loaded["nodes"][1]["type"], "provider_text_to_image")
        self.assertTrue(frappe.db.exists("AI Workflow Version", run["workflow_version"]))
        self.assertTrue(frappe.db.exists("AI Workflow Run", run["workflow_run"]))
        self.assertEqual(status["status"], "QUEUED")
        self.assertEqual(len(status["node_runs"]), 3)
        self.assertEqual(history["run"]["workflow_run"], run["workflow_run"])
        self.assertIn(run["workflow_run"], {row["name"] for row in queue["queued"]})

    def test_canvas_asset_view_api_flow_uses_real_asset_documents(self):
        ensure_canvas_provider_catalog()
        project = create_project()
        workflow = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            project=project.name,
            title="Canvas Asset Workflow",
            nodes=json.dumps(canvas_nodes()),
            edges=json.dumps(canvas_edges()),
            layout=json.dumps({"nodes": [{"id": "image_1", "x": 376, "y": 128}]}),
        )
        run = frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])
        image_node_run = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": run["workflow_run"], "node_id": "image_1"},
            "name",
        )
        asset = frappe.get_doc(
            {
                "doctype": "AI Asset",
                "project": project.name,
                "asset_type": "IMAGE",
                "url": "https://example.invalid/canvas-output.png",
                "mime_type": "image/png",
                "source_workflow_run": run["workflow_run"],
                "source_node_run": image_node_run,
                "metadata_json": json.dumps({"origin": "canvas-placeholder-test"}),
            }
        ).insert(ignore_permissions=True)

        history = frappe.call("slow_ai.api.runs.get_history", workflow_run=run["workflow_run"])
        viewed = frappe.call("slow_ai.api.assets.view", asset=asset.name)

        self.assertIn(asset.name, {row["name"] for row in history["assets"]})
        self.assertEqual(viewed["name"], asset.name)
        self.assertEqual(viewed["source_workflow_run"], run["workflow_run"])
        self.assertEqual(viewed["metadata"]["origin"], "canvas-placeholder-test")

    def test_canvas_model_metadata_api_returns_safe_pricing_only(self):
        model = frappe.get_doc(
            {
                "doctype": "AI Model",
                "model_id": unique("canvas/model"),
                "model_name": "Canvas Safety Model",
                "provider": "wavespeed",
                "status": "ENABLED",
                "modality": "TEXT_TO_IMAGE",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": "0.012"}),
            }
        ).insert(ignore_permissions=True)

        metadata = frappe.call("slow_ai.api.models.get_model_metadata", model_ids=json.dumps([model.name]))

        self.assertEqual(metadata["models"][model.name]["provider"], "wavespeed")
        self.assertTrue(metadata["models"][model.name]["pricing_known"])
        self.assertEqual(metadata["models"][model.name]["estimated_cost_usd"], "0.012")
        self.assertNotIn("pricing_json", metadata["models"][model.name])

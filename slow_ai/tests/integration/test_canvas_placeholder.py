import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.billing import create_top_up
from slow_ai.domain.exceptions import GraphValidationError, RunPreflightError


ALLOWED_CANVAS_METHODS = {
    "slow_ai.api.nodes.get_object_info",
    "slow_ai.api.workflows.get_workflow",
    "slow_ai.api.workflows.save_workflow",
    "slow_ai.api.runs.start_run",
    "slow_ai.api.runs.get_run_status",
    "slow_ai.api.runs.get_history",
    "slow_ai.api.queue.get_queue_status",
    "slow_ai.api.assets.upload",
    "slow_ai.api.assets.view",
    "slow_ai.api.models.get_model",
    "slow_ai.api.models.get_model_metadata",
    "slow_ai.api.models.list_models",
    "slow_ai.api.models.update_model_pricing",
    "slow_ai.api.models.update_model_status",
    "slow_ai.api.provider_accounts.list_accounts",
    "slow_ai.api.provider_accounts.get_account",
    "slow_ai.api.provider_accounts.create_account",
    "slow_ai.api.provider_accounts.set_default",
    "slow_ai.api.provider_accounts.disable_account",
    "slow_ai.api.templates.list_templates",
    "slow_ai.api.templates.get_template",
    "slow_ai.api.templates.save_template",
    "slow_ai.api.templates.create_workflow_from_template",
    "slow_ai.api.templates.submit_template_for_review",
    "slow_ai.api.templates.approve_template",
    "slow_ai.api.templates.reject_template",
    "slow_ai.api.templates.archive_template",
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


def tool_mode_nodes(text: str = "Tool mode prompt"):
    return [
        {
            "id": "prompt_1",
            "type": "text_prompt",
            "label": "Prompt",
            "position": {"x": 96, "y": 128},
            "config": {"text": text},
        },
        {
            "id": "tool_output_1",
            "type": "tool_output",
            "label": "Tool Output",
            "position": {"x": 376, "y": 128},
            "config": {
                "output_name": "answer",
                "description": "Primary tool output",
                "schema": {"type": "string"},
            },
        },
    ]


def tool_mode_edges():
    return [
        {
            "id": "edge_1",
            "source": "prompt_1",
            "source_port": "text",
            "target": "tool_output_1",
            "target_port": "text",
        }
    ]


def tool_mode_upload_nodes(asset_name: str):
    return [
        {
            "id": "asset_1",
            "type": "upload_asset",
            "label": "Input Asset",
            "position": {"x": 96, "y": 128},
            "config": {"asset": asset_name, "asset_type": "IMAGE"},
        },
        {
            "id": "tool_output_1",
            "type": "tool_output",
            "label": "Tool Output",
            "position": {"x": 376, "y": 128},
            "config": {
                "output_name": "image",
                "description": "Selected image asset",
                "schema": {"type": "string"},
            },
        },
    ]


def tool_mode_upload_edges():
    return [
        {
            "id": "edge_1",
            "source": "asset_1",
            "source_port": "image",
            "target": "tool_output_1",
            "target_port": "image",
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
        self.assertIn("data-role=\"draft-controls\"", page.script)
        self.assertIn("slow-ai-canvas__draft-controls", page.style)
        self.assertIn("slow-ai-canvas__asset-output", page.style)
        self.assertIn("slow-ai-canvas__asset-card", page.style)
        self.assertIn("slow-ai-canvas__asset-media", page.style)
        self.assertIn("slow-ai-canvas__asset-text-preview", page.style)
        self.assertIn("Provider Text to Image", page.script)
        self.assertIn("paletteCategories", page.script)
        self.assertIn('"input", "provider", "image", "video", "audio", "utility", "output"', page.script)
        self.assertIn("input_schema", page.script)
        self.assertIn("config_schema", page.script)
        self.assertIn("output_schema", page.script)
        self.assertIn("Add Node", page.script)
        self.assertIn("addNodeFromMetadata", page.script)
        self.assertIn("selectNode", page.script)
        self.assertIn("data-node-drag-handle", page.script)
        self.assertIn("startNodeDrag", page.script)
        self.assertIn("dragNode", page.script)
        self.assertIn("startVisualEdge", page.script)
        self.assertIn("completeVisualEdge", page.script)
        self.assertIn("data-port-direction", page.script)
        self.assertIn("delete-visual-edge", page.script)
        self.assertIn("portAnchor", page.script)
        self.assertIn("syncStageSize", page.script)
        self.assertIn("renderNodeEditor", page.script)
        self.assertIn("data-config-field", page.script)
        self.assertIn("updateSelectedNodeConfig", page.script)
        self.assertIn("data-position-field", page.script)
        self.assertIn("captureLayout", page.script)
        self.assertIn("addEdgeFromEditor", page.script)
        self.assertIn("deleteEdge", page.script)
        self.assertIn("deleteSelectedNode", page.script)
        self.assertIn("portsCompatible", page.script)
        self.assertIn("draftWarnings", page.script)
        self.assertIn("renderRunSummary", page.script)
        self.assertIn("renderProviderJobs", page.script)
        self.assertIn("renderLedgerSummary", page.script)
        self.assertIn("renderRunErrors", page.script)
        self.assertIn("renderRunTimeline", page.script)
        self.assertIn("safeErrorMessage", page.script)
        self.assertIn("sanitizeErrorText", page.script)
        self.assertIn("slow_ai_workflow_run_update", page.script)
        self.assertIn("slow_ai_node_run_update", page.script)
        self.assertIn("slow_ai_provider_job_update", page.script)
        self.assertIn('"PENDING", "READY", "RUNNING", "WAITING_PROVIDER", "SUCCEEDED", "FAILED", "SKIPPED", "CANCELLED"', page.script)
        self.assertIn("slow-ai-canvas__draft-warning", page.style)
        self.assertIn("slow-ai-canvas__edge-row", page.style)
        self.assertIn("slow-ai-canvas__node-header", page.style)
        self.assertIn("slow-ai-canvas__port", page.style)
        self.assertIn("slow-ai-canvas__edge-delete", page.style)
        self.assertIn("slow-ai-canvas__node-editor", page.style)
        self.assertIn("slow-ai-canvas__provider-jobs", page.style)
        self.assertIn("slow-ai-canvas__ledger-summary", page.style)
        self.assertIn("slow-ai-canvas__run-errors", page.style)
        self.assertIn("slow-ai-canvas__run-timeline", page.style)
        self.assertIn("slow-ai-canvas__safe-error", page.style)
        self.assertIn("Refresh Run", page.script)
        self.assertIn("renderAssetCard", page.script)
        self.assertIn("renderAssetPreview", page.script)
        self.assertIn("copyAssetUrl", page.script)
        self.assertIn("refreshAssetCard", page.script)
        self.assertIn("Open Asset", page.script)
        self.assertIn("Copy URL", page.script)
        self.assertIn("Refresh Asset", page.script)
        self.assertIn("<img", page.script)
        self.assertIn("<video", page.script)
        self.assertIn("<audio", page.script)
        self.assertIn("assetTextSummary", page.script)
        self.assertIn("This workflow may call an external provider and spend credits.", page.script)
        self.assertIn("cost unknown", page.script)
        self.assertIn("frappe.confirm", page.script)
        self.assertIn("Template Library", page.script)
        self.assertIn("loadTemplates", page.script)
        self.assertIn("renderTemplateLibrary", page.script)
        self.assertIn("saveCurrentWorkflowAsTemplate", page.script)
        self.assertIn("loadTemplatePreview", page.script)
        self.assertIn("createWorkflowFromTemplate", page.script)
        self.assertIn("submitTemplateForReview", page.script)
        self.assertIn("approveTemplate", page.script)
        self.assertIn("rejectTemplate", page.script)
        self.assertIn("archiveTemplate", page.script)
        self.assertIn("Submit Review", page.script)
        self.assertIn("Approve", page.script)
        self.assertIn("Reject", page.script)
        self.assertIn("Archive", page.script)
        self.assertIn("Save Current Workflow as Template", page.script)
        self.assertIn("Load Template Preview", page.script)
        self.assertIn("Create Workflow from Template", page.script)
        self.assertIn("frappe.prompt", page.script)
        self.assertIn("Tool Mode", page.script)
        self.assertIn("renderToolModePanel", page.script)
        self.assertIn("loadToolModeTemplate", page.script)
        self.assertIn("runToolModeForm", page.script)
        self.assertIn("uploadToolModeAsset", page.script)
        self.assertIn("uploadToolModeFile", page.script)
        self.assertIn("previewToolModeAsset", page.script)
        self.assertIn("slow_ai.api.assets.upload", page.script)
        self.assertIn("slow_ai.api.assets.view", page.script)
        self.assertIn("collectToolModeValues", page.script)
        self.assertIn("applyToolModeValues", page.script)
        self.assertIn("Run Tool", page.script)
        self.assertIn("AI Asset name", page.script)
        self.assertIn("Create AI Asset", page.script)
        self.assertIn("Upload File", page.script)
        self.assertIn("Preview Selected Asset", page.script)
        self.assertIn("Provider Accounts", page.script)
        self.assertIn("renderProviderAccountsPanel", page.script)
        self.assertIn("createProviderAccount", page.script)
        self.assertIn("setDefaultProviderAccount", page.script)
        self.assertIn("disableProviderAccount", page.script)
        self.assertIn("viewProviderAccount", page.script)
        self.assertIn("slow_ai.api.provider_accounts.list_accounts", page.script)
        self.assertIn("slow_ai.api.provider_accounts.get_account", page.script)
        self.assertIn("slow_ai.api.provider_accounts.create_account", page.script)
        self.assertIn("slow_ai.api.provider_accounts.set_default", page.script)
        self.assertIn("slow_ai.api.provider_accounts.disable_account", page.script)
        self.assertIn("API keys are never displayed after save.", page.script)
        self.assertIn("slow-ai-canvas__provider-accounts", page.style)
        self.assertIn("slow-ai-canvas__provider-account-row", page.style)
        self.assertIn("Model Catalog", page.script)
        self.assertIn("renderModelCatalogPanel", page.script)
        self.assertIn("loadModelDetail", page.script)
        self.assertIn("updateModelStatus", page.script)
        self.assertIn("updateModelPricing", page.script)
        self.assertIn("slow_ai.api.models.list_models", page.script)
        self.assertIn("slow_ai.api.models.get_model", page.script)
        self.assertIn("slow_ai.api.models.update_model_status", page.script)
        self.assertIn("slow_ai.api.models.update_model_pricing", page.script)
        self.assertIn("Disabled model cannot pass run preflight.", page.script)
        self.assertIn("Pricing unknown; strict preflight will reject this model.", page.script)
        self.assertIn("slow-ai-canvas__model-catalog", page.style)
        self.assertIn("slow-ai-canvas__model-warning", page.style)
        for method in ALLOWED_CANVAS_METHODS:
            self.assertIn(method, page.script)
        for fragment in FORBIDDEN_CANVAS_FRAGMENTS:
            self.assertNotIn(fragment, page.script)

    def test_canvas_api_flow_saves_starts_and_reads_real_run_records(self):
        ensure_canvas_provider_catalog()
        project = create_project()
        create_top_up(project.name, "0.05", "Canvas API flow credit")
        object_info = frappe.call("slow_ai.api.nodes.get_object_info")
        self.assertIn("text_prompt", object_info["nodes"])
        self.assertEqual(object_info["nodes"]["text_prompt"]["category"], "input")
        self.assertEqual(object_info["nodes"]["provider_text_to_image"]["category"], "provider")
        self.assertEqual(object_info["nodes"]["export_output"]["category"], "output")
        self.assertIn("prompt", object_info["nodes"]["provider_text_to_image"]["input_schema"])
        self.assertIn("model", object_info["nodes"]["provider_text_to_image"]["config_schema"])
        self.assertIn("image", object_info["nodes"]["provider_text_to_image"]["output_schema"])

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

    def test_canvas_graph_editor_assets_are_draft_only_and_backend_rejects_invalid_graph(self):
        frappe.reload_doc("slow_ai", "page", "slow_ai_canvas")
        page = frappe.get_doc("Page", "slow-ai-canvas")
        page.load_assets()

        self.assertIn("this.nodes.push(node)", page.script)
        self.assertIn("this.edges.push({", page.script)
        self.assertIn("this.nodes = this.nodes.filter", page.script)
        self.assertIn("this.edges = this.edges.filter", page.script)
        self.assertIn("startVisualEdge", page.script)
        self.assertIn("completeVisualEdge", page.script)
        self.assertIn("startNodeDrag", page.script)
        self.assertIn("captureLayout", page.script)
        self.assertIn('frappe.call("slow_ai.api.workflows.save_workflow"', page.script)
        self.assertIn('frappe.call("slow_ai.api.runs.start_run"', page.script)
        for forbidden in ("frappe.db", "providers/wavespeed", "api.wavespeed.ai", "WAVESPEED_API_KEY"):
            self.assertNotIn(forbidden, page.script)

        project = create_project()
        invalid_edges = [
            {
                "id": "edge_1",
                "source": "prompt_1",
                "source_port": "text",
                "target": "output_1",
                "target_port": "image",
            }
        ]
        with self.assertRaises(GraphValidationError):
            frappe.call(
                "slow_ai.api.workflows.save_workflow",
                project=project.name,
                title="Canvas Invalid Graph",
                nodes=json.dumps([canvas_nodes()[0], canvas_nodes()[2]]),
                edges=json.dumps(invalid_edges),
                layout=json.dumps({"nodes": [{"id": "output_1", "x": 656, "y": 128}]}),
            )

    def test_canvas_template_library_uses_backend_apis_without_starting_runs(self):
        frappe.reload_doc("slow_ai", "page", "slow_ai_canvas")
        page = frappe.get_doc("Page", "slow-ai-canvas")
        page.load_assets()

        self.assertIn("slow_ai.api.templates.list_templates", page.script)
        self.assertIn("slow_ai.api.templates.get_template", page.script)
        self.assertIn("slow_ai.api.templates.save_template", page.script)
        self.assertIn("slow_ai.api.templates.create_workflow_from_template", page.script)
        self.assertIn('frappe.call("slow_ai.api.runs.start_run"', page.script)
        self.assertIn("This workflow may call an external provider and spend credits.", page.script)
        for forbidden in ("frappe.db", "providers/wavespeed", "api.wavespeed.ai", "WAVESPEED_API_KEY"):
            self.assertNotIn(forbidden, page.script)

        project = create_project()
        before_runs = frappe.db.count("AI Workflow Run")
        before_versions = frappe.db.count("AI Workflow Version")
        before_provider_jobs = frappe.db.count("AI Provider Job")

        template = frappe.call(
            "slow_ai.api.templates.save_template",
            template_name=unique("Canvas Template"),
            status="PUBLISHED",
            category="Canvas",
            description="Canvas template library test",
            nodes=json.dumps(canvas_nodes()),
            edges=json.dumps(canvas_edges()),
            layout=json.dumps({"nodes": [{"id": "image_1", "x": 376, "y": 128}]}),
        )
        listed = frappe.call("slow_ai.api.templates.list_templates", status="PUBLISHED", category="Canvas")
        loaded = frappe.call("slow_ai.api.templates.get_template", template=template["name"])
        created = frappe.call(
            "slow_ai.api.templates.create_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Workflow From Canvas Template",
        )

        self.assertTrue(frappe.db.exists("AI Workflow Template", template["name"]))
        self.assertIn(template["name"], {row["name"] for row in listed["templates"]})
        self.assertEqual(loaded["name"], template["name"])
        self.assertEqual(loaded["nodes"][1]["type"], "provider_text_to_image")
        self.assertTrue(frappe.db.exists("AI Workflow", created["name"]))
        self.assertEqual(created["status"], "DRAFT")
        self.assertEqual(frappe.db.get_value("AI Workflow", created["name"], "project"), project.name)
        self.assertEqual(frappe.db.count("AI Workflow Run"), before_runs)
        self.assertEqual(frappe.db.count("AI Workflow Version"), before_versions)
        self.assertEqual(frappe.db.count("AI Provider Job"), before_provider_jobs)

        ensure_canvas_provider_catalog()
        create_top_up(project.name, "0.05", "Canvas template run credit")
        run = frappe.call("slow_ai.api.runs.start_run", workflow=created["name"])

        self.assertTrue(frappe.db.exists("AI Workflow Run", run["workflow_run"]))
        self.assertTrue(frappe.db.exists("AI Workflow Version", run["workflow_version"]))

    def test_canvas_tool_mode_form_flow_uses_template_draft_save_and_start_run(self):
        frappe.reload_doc("slow_ai", "page", "slow_ai_canvas")
        page = frappe.get_doc("Page", "slow-ai-canvas")
        page.load_assets()

        self.assertIn("Tool Mode", page.script)
        self.assertIn("slow_ai.api.templates.list_templates", page.script)
        self.assertIn("slow_ai.api.templates.get_template", page.script)
        self.assertIn("slow_ai.api.templates.create_workflow_from_template", page.script)
        self.assertIn("slow_ai.api.workflows.save_workflow", page.script)
        self.assertIn("slow_ai.api.runs.start_run", page.script)
        for forbidden in ("frappe.db", "providers/wavespeed", "api.wavespeed.ai", "WAVESPEED_API_KEY"):
            self.assertNotIn(forbidden, page.script)

        project = create_project()
        before_provider_jobs = frappe.db.count("AI Provider Job")
        before_runs = frappe.db.count("AI Workflow Run")
        template = frappe.call(
            "slow_ai.api.templates.save_template",
            template_name=unique("Canvas Tool Template"),
            status="PUBLISHED",
            category="Tool",
            description="Canvas Tool Mode template",
            nodes=json.dumps(tool_mode_nodes("Template prompt")),
            edges=json.dumps(tool_mode_edges()),
            layout=json.dumps({"nodes": [{"id": "prompt_1", "x": 96, "y": 128}]}),
        )
        loaded = frappe.call("slow_ai.api.templates.get_template", template=template["name"])
        draft = frappe.call(
            "slow_ai.api.templates.create_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Canvas Tool Mode Run",
        )
        draft["nodes"][0]["config"]["text"] = "Prompt entered through Tool Mode"
        saved = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            workflow=draft["name"],
            project=project.name,
            title=draft["title"],
            nodes=json.dumps(draft["nodes"]),
            edges=json.dumps(draft["edges"]),
            layout=json.dumps(draft["layout"]),
        )
        run = frappe.call("slow_ai.api.runs.start_run", workflow=saved["name"])

        self.assertEqual(loaded["nodes"][0]["config"]["text"], "Template prompt")
        self.assertEqual(saved["nodes"][0]["config"]["text"], "Prompt entered through Tool Mode")
        self.assertEqual(frappe.db.count("AI Provider Job"), before_provider_jobs)
        self.assertEqual(frappe.db.count("AI Workflow Run"), before_runs + 1)
        self.assertTrue(frappe.db.exists("AI Workflow", saved["name"]))
        self.assertTrue(frappe.db.exists("AI Workflow Version", run["workflow_version"]))
        self.assertTrue(frappe.db.exists("AI Workflow Run", run["workflow_run"]))

    def test_canvas_tool_mode_provider_template_still_uses_backend_preflight(self):
        project = create_project()
        before_provider_jobs = frappe.db.count("AI Provider Job")
        template = frappe.call(
            "slow_ai.api.templates.save_template",
            template_name=unique("Canvas Tool Provider Template"),
            status="PUBLISHED",
            category="Tool",
            description="Provider template preflight test",
            nodes=json.dumps(
                [
                    {
                        "id": "prompt_1",
                        "type": "text_prompt",
                        "label": "Prompt",
                        "position": {"x": 96, "y": 128},
                        "config": {"text": "Provider prompt"},
                    },
                    {
                        "id": "provider_text_to_image_1",
                        "type": "provider_text_to_image",
                        "label": "Provider Text To Image",
                        "position": {"x": 376, "y": 128},
                        "config": {"provider": "no_account_provider", "model": "missing-model"},
                    },
                    {
                        "id": "output_1",
                        "type": "export_output",
                        "label": "Output",
                        "position": {"x": 656, "y": 128},
                        "config": {},
                    },
                ]
            ),
            edges=json.dumps(
                [
                    {
                        "id": "edge_1",
                        "source": "prompt_1",
                        "source_port": "text",
                        "target": "provider_text_to_image_1",
                        "target_port": "prompt",
                    },
                    {
                        "id": "edge_2",
                        "source": "provider_text_to_image_1",
                        "source_port": "image",
                        "target": "output_1",
                        "target_port": "image",
                    },
                ]
            ),
            layout=json.dumps({"nodes": [{"id": "provider_text_to_image_1", "x": 376, "y": 128}]}),
        )
        draft = frappe.call(
            "slow_ai.api.templates.create_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Canvas Tool Provider Run",
        )

        with self.assertRaises(RunPreflightError):
            frappe.call("slow_ai.api.runs.start_run", workflow=draft["name"])

        self.assertEqual(frappe.db.count("AI Provider Job"), before_provider_jobs)
        self.assertFalse(frappe.db.exists("AI Workflow Run", {"workflow": draft["name"]}))

    def test_canvas_tool_mode_upload_asset_uses_asset_api_and_persists_selected_asset(self):
        frappe.reload_doc("slow_ai", "page", "slow_ai_canvas")
        page = frappe.get_doc("Page", "slow-ai-canvas")
        page.load_assets()

        self.assertIn("slow_ai.api.assets.upload", page.script)
        self.assertIn("slow_ai.api.assets.view", page.script)
        self.assertIn("uploadToolModeAsset", page.script)
        self.assertIn("uploadToolModeFile", page.script)
        self.assertIn("previewToolModeAsset", page.script)
        self.assertIn("renderToolModeAssetPreview", page.script)
        self.assertIn("slow_ai.api.runs.start_run", page.script)
        for forbidden in ("frappe.db", "providers/wavespeed", "api.wavespeed.ai", "WAVESPEED_API_KEY"):
            self.assertNotIn(forbidden, page.script)

        project = create_project()
        placeholder = frappe.call(
            "slow_ai.api.assets.upload",
            project=project.name,
            asset_type="IMAGE",
            url="https://example.invalid/placeholder.png",
            mime_type="image/png",
            metadata=json.dumps({"origin": "tool-mode-placeholder"}),
        )
        before_provider_jobs = frappe.db.count("AI Provider Job")
        before_runs = frappe.db.count("AI Workflow Run")
        template = frappe.call(
            "slow_ai.api.templates.save_template",
            template_name=unique("Canvas Tool Upload Template"),
            status="PUBLISHED",
            category="Tool",
            description="Tool Mode upload asset template",
            nodes=json.dumps(tool_mode_upload_nodes(placeholder["name"])),
            edges=json.dumps(tool_mode_upload_edges()),
            layout=json.dumps({"nodes": [{"id": "asset_1", "x": 96, "y": 128}]}),
        )
        loaded = frappe.call("slow_ai.api.templates.get_template", template=template["name"])
        uploaded = frappe.call(
            "slow_ai.api.assets.upload",
            project=project.name,
            asset_type="IMAGE",
            url="https://example.invalid/tool-mode-selected.png",
            mime_type="image/png",
            metadata=json.dumps({"origin": "tool-mode-upload"}),
        )
        viewed = frappe.call("slow_ai.api.assets.view", asset=uploaded["name"])
        draft = frappe.call(
            "slow_ai.api.templates.create_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Canvas Tool Upload Run",
        )
        draft["nodes"][0]["config"]["asset"] = uploaded["name"]
        draft["nodes"][0]["config"]["asset_type"] = uploaded["asset_type"]
        saved = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            workflow=draft["name"],
            project=project.name,
            title=draft["title"],
            nodes=json.dumps(draft["nodes"]),
            edges=json.dumps(draft["edges"]),
            layout=json.dumps(draft["layout"]),
        )
        run = frappe.call("slow_ai.api.runs.start_run", workflow=saved["name"])

        self.assertEqual(loaded["nodes"][0]["config"]["asset"], placeholder["name"])
        self.assertTrue(frappe.db.exists("AI Asset", uploaded["name"]))
        self.assertEqual(viewed["url"], "https://example.invalid/tool-mode-selected.png")
        self.assertEqual(viewed["metadata"]["origin"], "tool-mode-upload")
        self.assertEqual(saved["nodes"][0]["config"]["asset"], uploaded["name"])
        self.assertEqual(saved["nodes"][0]["config"]["asset_type"], "IMAGE")
        self.assertEqual(frappe.db.count("AI Provider Job"), before_provider_jobs)
        self.assertEqual(frappe.db.count("AI Workflow Run"), before_runs + 1)
        self.assertTrue(frappe.db.exists("AI Workflow Version", run["workflow_version"]))

    def test_added_provider_node_still_uses_backend_preflight_on_start(self):
        project = create_project()
        saved = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            project=project.name,
            title="Canvas Added Provider Node Workflow",
            nodes=json.dumps(
                [
                    {
                        "id": "prompt_1",
                        "type": "text_prompt",
                        "label": "Prompt",
                        "position": {"x": 96, "y": 128},
                        "config": {"text": "Canvas prompt"},
                    },
                    {
                        "id": "provider_text_to_image_2",
                        "type": "provider_text_to_image",
                        "label": "Provider Text To Image",
                        "position": {"x": 376, "y": 128},
                        "config": {"provider": "no_account_provider", "model": "missing-model"},
                    },
                    {
                        "id": "output_1",
                        "type": "export_output",
                        "label": "Output",
                        "position": {"x": 656, "y": 128},
                        "config": {},
                    },
                ]
            ),
            edges=json.dumps(
                [
                    {
                        "id": "edge_1",
                        "source": "prompt_1",
                        "source_port": "text",
                        "target": "provider_text_to_image_2",
                        "target_port": "prompt",
                    },
                    {
                        "id": "edge_2",
                        "source": "provider_text_to_image_2",
                        "source_port": "image",
                        "target": "output_1",
                        "target_port": "image",
                    },
                ]
            ),
            layout=json.dumps({"nodes": [{"id": "provider_text_to_image_2", "x": 376, "y": 128}]}),
        )
        provider_job_count = frappe.db.count("AI Provider Job")

        with self.assertRaises(RunPreflightError):
            frappe.call("slow_ai.api.runs.start_run", workflow=saved["name"])

        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)
        self.assertFalse(frappe.db.exists("AI Workflow Run", {"workflow": saved["name"]}))

    def test_canvas_asset_view_api_flow_uses_real_asset_documents(self):
        ensure_canvas_provider_catalog()
        project = create_project()
        create_top_up(project.name, "0.05", "Canvas asset view credit")
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
        self.assertIn("created", viewed)
        self.assertIn("modified", viewed)

    def test_canvas_asset_preview_paths_use_asset_view_payloads(self):
        frappe.reload_doc("slow_ai", "page", "slow_ai_canvas")
        page = frappe.get_doc("Page", "slow-ai-canvas")
        page.load_assets()

        self.assertIn('frappe.call("slow_ai.api.assets.view"', page.script)
        self.assertIn("renderAssetCard", page.script)
        self.assertIn("renderAssetMetaRow", page.script)
        self.assertIn("assetUrl(asset)", page.script)
        self.assertIn("asset.source_workflow_run", page.script)
        self.assertIn("asset.source_node_run", page.script)
        self.assertIn("asset.source_provider_job", page.script)
        self.assertIn("asset.duration_seconds", page.script)
        self.assertIn("asset.width && asset.height", page.script)

        project = create_project()
        ensure_canvas_provider_catalog()
        create_top_up(project.name, "0.05", "Canvas asset preview credit")
        workflow = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            project=project.name,
            title="Canvas Asset Preview Workflow",
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
        provider_job = frappe.get_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": image_node_run,
                "provider": "preview_provider",
                "status": "SUCCEEDED",
                "idempotency_key": unique("canvas-preview-job"),
            }
        ).insert(ignore_permissions=True)
        asset_specs = [
            ("IMAGE", "https://example.invalid/preview.png", "image/png", {"width": 320, "height": 240}),
            ("VIDEO", "https://example.invalid/preview.mp4", "video/mp4", {"duration_seconds": 2.5}),
            ("AUDIO", "https://example.invalid/preview.mp3", "audio/mpeg", {"duration_seconds": 1.25}),
            ("JSON", "", "application/json", {"metadata_json": json.dumps({"json": {"answer": 42}})}),
            ("TEXT", "", "text/plain", {"metadata_json": json.dumps({"text": "Preview text"})}),
        ]
        assets = []
        for asset_type, url, mime_type, extra in asset_specs:
            values = {
                "doctype": "AI Asset",
                "project": project.name,
                "asset_type": asset_type,
                "url": url,
                "mime_type": mime_type,
                "source_workflow_run": run["workflow_run"],
                "source_node_run": image_node_run,
                "source_provider_job": provider_job.name,
                "metadata_json": json.dumps({"origin": "canvas-preview-test"}),
            }
            values.update(extra)
            assets.append(frappe.get_doc(values).insert(ignore_permissions=True))

        viewed_assets = [frappe.call("slow_ai.api.assets.view", asset=asset.name) for asset in assets]

        self.assertEqual({row["asset_type"] for row in viewed_assets}, {"IMAGE", "VIDEO", "AUDIO", "JSON", "TEXT"})
        for viewed in viewed_assets:
            self.assertEqual(viewed["source_workflow_run"], run["workflow_run"])
            self.assertEqual(viewed["source_node_run"], image_node_run)
            self.assertEqual(viewed["source_provider_job"], provider_job.name)
            self.assertIn("created", viewed)
            self.assertIn("modified", viewed)
        image = next(row for row in viewed_assets if row["asset_type"] == "IMAGE")
        video = next(row for row in viewed_assets if row["asset_type"] == "VIDEO")
        text = next(row for row in viewed_assets if row["asset_type"] == "TEXT")
        self.assertEqual(image["width"], 320)
        self.assertEqual(image["height"], 240)
        self.assertEqual(video["duration_seconds"], 2.5)
        self.assertEqual(text["metadata"]["text"], "Preview text")

    def test_canvas_run_monitor_history_uses_real_provider_asset_ledger_and_error_records(self):
        frappe.reload_doc("slow_ai", "page", "slow_ai_canvas")
        page = frappe.get_doc("Page", "slow-ai-canvas")
        page.load_assets()
        self.assertIn('frappe.call("slow_ai.api.runs.get_run_status"', page.script)
        self.assertIn('frappe.call("slow_ai.api.runs.get_history"', page.script)
        self.assertIn('frappe.call("slow_ai.api.assets.view"', page.script)
        self.assertIn("Provider submitted", page.script)
        self.assertIn("Provider completed", page.script)
        self.assertIn("Asset created", page.script)
        self.assertIn("Run completed", page.script)
        self.assertIn("Run failed", page.script)

        ensure_canvas_provider_catalog()
        project = create_project()
        create_top_up(project.name, "0.05", "Canvas monitor credit")
        workflow = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            project=project.name,
            title="Canvas Monitor Workflow",
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
        provider_job = frappe.get_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": image_node_run,
                "provider": "wavespeed",
                "model": "wavespeed-ai/flux-dev",
                "external_job_id": unique("external"),
                "status": "FAILED",
                "idempotency_key": unique("canvas-monitor-job"),
                "cost_usd": 0.012,
                "request_json": json.dumps({"prompt": "Canvas prompt"}),
                "raw_error_json": json.dumps(
                    {
                        "message": "Provider request failed at https://provider.example.invalid",
                        "code": "provider_error",
                        "api_key": "should-not-render",
                    }
                ),
            }
        ).insert(ignore_permissions=True)
        asset = frappe.get_doc(
            {
                "doctype": "AI Asset",
                "project": project.name,
                "asset_type": "IMAGE",
                "url": "https://example.invalid/canvas-monitor-output.png",
                "mime_type": "image/png",
                "source_workflow_run": run["workflow_run"],
                "source_node_run": image_node_run,
                "source_provider_job": provider_job.name,
                "metadata_json": json.dumps({"origin": "canvas-monitor-test"}),
            }
        ).insert(ignore_permissions=True)
        ledger = frappe.get_doc(
            {
                "doctype": "AI Credit Ledger",
                "project": project.name,
                "workflow_run": run["workflow_run"],
                "node_run": image_node_run,
                "provider_job": provider_job.name,
                "ledger_type": "DEBIT",
                "amount_usd": 0.012,
                "currency": "USD",
                "description": "Canvas monitor cost",
            }
        ).insert(ignore_permissions=True)

        status = frappe.call("slow_ai.api.runs.get_run_status", workflow_run=run["workflow_run"])
        history = frappe.call("slow_ai.api.runs.get_history", workflow_run=run["workflow_run"])
        viewed = frappe.call("slow_ai.api.assets.view", asset=asset.name)

        self.assertEqual(status["workflow_run"], run["workflow_run"])
        self.assertIn(image_node_run, {row["name"] for row in history["node_runs"]})
        self.assertIn(provider_job.name, {row["name"] for row in history["provider_jobs"]})
        self.assertIn(asset.name, {row["name"] for row in history["assets"]})
        self.assertIn(ledger.name, {row["name"] for row in history["ledger"]})
        self.assertEqual(history["provider_jobs"][0]["error"]["code"], "provider_error")
        self.assertEqual(viewed["url"], "https://example.invalid/canvas-monitor-output.png")

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

    def test_canvas_model_catalog_ui_uses_safe_model_apis_and_preflight_guards(self):
        frappe.reload_doc("slow_ai", "page", "slow_ai_canvas")
        page = frappe.get_doc("Page", "slow-ai-canvas")
        page.load_assets()

        for method in (
            "slow_ai.api.models.list_models",
            "slow_ai.api.models.get_model",
            "slow_ai.api.models.update_model_status",
            "slow_ai.api.models.update_model_pricing",
        ):
            self.assertIn(method, page.script)
        self.assertIn("Model Catalog", page.script)
        self.assertIn("Inspect Model", page.script)
        self.assertIn("Disable Model", page.script)
        self.assertIn("Save Pricing", page.script)
        self.assertIn("Disabled model cannot pass run preflight.", page.script)
        self.assertIn("Pricing unknown; strict preflight will reject this model.", page.script)
        self.assertNotIn("api_key_secret", page.script)
        for forbidden in ("frappe.db", "providers/wavespeed", "api.wavespeed.ai", "WAVESPEED_API_KEY"):
            self.assertNotIn(forbidden, page.script)

        project = create_project()
        provider = unique("canvas-model-ui-provider")
        account = frappe.get_doc(
            {
                "doctype": "AI Provider Account",
                "provider": provider,
                "account_label": unique("Canvas Model Account"),
                "api_key_secret": "canvas-model-test-key",
                "is_default": 1,
                "status": "ACTIVE",
            }
        ).insert(ignore_permissions=True)
        model = frappe.get_doc(
            {
                "doctype": "AI Model",
                "model_id": unique(f"{provider}/model"),
                "model_slug": unique(f"{provider}-slug"),
                "model_name": "Canvas Model Catalog",
                "provider": provider,
                "status": "ENABLED",
                "node_type": "provider_text_to_image",
                "category": "provider",
                "modality": "TEXT_TO_IMAGE",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": "0.01", "currency": "USD"}),
                "capabilities_json": json.dumps({"text_to_image": True}),
                "input_metadata_json": json.dumps({"prompt": "text"}),
                "output_metadata_json": json.dumps({"image": "AI Asset"}),
            }
        ).insert(ignore_permissions=True)
        provider_job_count = frappe.db.count("AI Provider Job")

        listed = frappe.call(
            "slow_ai.api.models.list_models",
            provider=provider,
            status="ALL",
            node_type="provider_text_to_image",
            category="provider",
        )
        detail = frappe.call("slow_ai.api.models.get_model", model=model.model_slug)
        disabled = frappe.call("slow_ai.api.models.update_model_status", model=model.name, status="DISABLED")
        unpriced = frappe.call("slow_ai.api.models.update_model_pricing", model=model.name, amount_usd="", unit="run", currency="USD")

        self.assertIn(model.name, {row["name"] for row in listed["models"]})
        self.assertEqual(detail["model"]["name"], model.name)
        self.assertEqual(disabled["model"]["status"], "DISABLED")
        self.assertFalse(unpriced["model"]["pricing_known"])
        serialized = json.dumps({"listed": listed, "detail": detail, "disabled": disabled, "unpriced": unpriced}, default=str)
        self.assertNotIn("api_key_secret", serialized)
        self.assertNotIn(account.get_password("api_key_secret"), serialized)
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)

        workflow = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            project=project.name,
            title="Canvas Model Catalog Guard Workflow",
            nodes=json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Canvas model guard"}},
                    {
                        "id": "provider_1",
                        "type": "provider_text_to_image",
                        "config": {"provider": provider, "model": model.name},
                    },
                    {"id": "output_1", "type": "export_output", "config": {}},
                ]
            ),
            edges=json.dumps(
                [
                    {
                        "id": "edge_1",
                        "source": "prompt_1",
                        "source_port": "text",
                        "target": "provider_1",
                        "target_port": "prompt",
                    },
                    {
                        "id": "edge_2",
                        "source": "provider_1",
                        "source_port": "image",
                        "target": "output_1",
                        "target_port": "image",
                    },
                ]
            ),
            layout=json.dumps({"nodes": []}),
        )
        with self.assertRaises(RunPreflightError):
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)

    def test_canvas_provider_account_ui_uses_safe_backend_apis(self):
        frappe.reload_doc("slow_ai", "page", "slow_ai_canvas")
        page = frappe.get_doc("Page", "slow-ai-canvas")
        page.load_assets()

        for method in (
            "slow_ai.api.provider_accounts.list_accounts",
            "slow_ai.api.provider_accounts.get_account",
            "slow_ai.api.provider_accounts.create_account",
            "slow_ai.api.provider_accounts.set_default",
            "slow_ai.api.provider_accounts.disable_account",
        ):
            self.assertIn(method, page.script)
        self.assertIn("type=\"password\"", page.script)
        self.assertIn("API keys are never displayed after save.", page.script)
        self.assertNotIn("api_key_secret", page.script)
        for forbidden in ("frappe.db", "providers/wavespeed", "api.wavespeed.ai", "WAVESPEED_API_KEY"):
            self.assertNotIn(forbidden, page.script)

        project = create_project()
        provider = unique("canvas-byok-provider")
        secret = unique("canvas-byok-secret")
        provider_job_count = frappe.db.count("AI Provider Job")
        first = frappe.call(
            "slow_ai.api.provider_accounts.create_account",
            provider=provider,
            account_label="Canvas BYOK Account",
            api_key=secret,
            project=project.name,
            is_default=1,
        )
        second = frappe.call(
            "slow_ai.api.provider_accounts.create_account",
            provider=provider,
            account_label="Canvas BYOK Account 2",
            api_key=unique("canvas-byok-secret"),
            project=project.name,
            is_default=0,
        )
        listed = frappe.call(
            "slow_ai.api.provider_accounts.list_accounts",
            provider=provider,
            project=project.name,
            include_disabled=1,
        )
        fetched = frappe.call("slow_ai.api.provider_accounts.get_account", account=first["account"]["name"])
        defaulted = frappe.call("slow_ai.api.provider_accounts.set_default", account=second["account"]["name"])
        disabled = frappe.call("slow_ai.api.provider_accounts.disable_account", account=second["account"]["name"])

        serialized = json.dumps(
            {
                "first": first,
                "second": second,
                "listed": listed,
                "fetched": fetched,
                "defaulted": defaulted,
                "disabled": disabled,
            },
            default=str,
        )
        self.assertEqual(frappe.get_doc("AI Provider Account", first["account"]["name"]).get_password("api_key_secret"), secret)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("api_key_secret", serialized)
        self.assertNotIn("api_key", serialized)
        self.assertIn(first["account"]["name"], {row["name"] for row in listed["accounts"]})
        self.assertEqual(defaulted["account"]["is_default"], 1)
        self.assertEqual(disabled["account"]["status"], "DISABLED")
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)

        model = frappe.get_doc(
            {
                "doctype": "AI Model",
                "model_id": unique(f"{provider}/model"),
                "model_name": "Canvas BYOK Model",
                "provider": provider,
                "status": "ENABLED",
                "node_type": "provider_text_to_image",
                "category": "provider",
                "modality": "TEXT_TO_IMAGE",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": "0.00"}),
            }
        ).insert(ignore_permissions=True)
        workflow = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            project=project.name,
            title="Canvas BYOK Disabled Account Workflow",
            nodes=json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Canvas BYOK"}},
                    {
                        "id": "provider_1",
                        "type": "provider_text_to_image",
                        "config": {
                            "provider": provider,
                            "model": model.name,
                            "provider_account": second["account"]["name"],
                        },
                    },
                    {"id": "output_1", "type": "export_output", "config": {}},
                ]
            ),
            edges=json.dumps(
                [
                    {
                        "id": "edge_1",
                        "source": "prompt_1",
                        "source_port": "text",
                        "target": "provider_1",
                        "target_port": "prompt",
                    },
                    {
                        "id": "edge_2",
                        "source": "provider_1",
                        "source_port": "image",
                        "target": "output_1",
                        "target_port": "image",
                    },
                ]
            ),
            layout=json.dumps({"nodes": []}),
        )

        with self.assertRaises(RunPreflightError):
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)
        self.assertFalse(frappe.db.exists("AI Workflow Run", {"workflow": workflow["name"]}))

import json
import re
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import update_password

from slow_ai.domain.exceptions import RunPreflightError
from slow_ai.workers.run_workflow import run_workflow


ALLOWED_PUBLIC_TOOL_METHODS = {
    "slow_ai.api.public_tools.list_templates",
    "slow_ai.api.public_tools.get_template",
    "slow_ai.api.public_tools.create_workflow_from_template",
    "slow_ai.api.workflows.save_workflow",
    "slow_ai.api.runs.start_run",
    "slow_ai.api.runs.get_run_status",
    "slow_ai.api.runs.get_history",
    "slow_ai.api.assets.upload",
    "slow_ai.api.assets.view",
    "slow_ai.api.billing.get_balance",
    "slow_ai.api.models.get_model_metadata",
}

FORBIDDEN_PUBLIC_TOOL_FRAGMENTS = (
    "ProviderAdapter",
    "ProviderRegistry",
    "WAVESPEED_API_KEY",
    "REPLICATE_API_KEY",
    "api_key_secret",
    "Authorization: Bearer",
    "api.wavespeed.ai",
    "api.replicate.com",
    "WorkflowExecutor",
    "run_workflow",
    "submit_job",
    "poll_job",
    "AI Provider Job",
    "AI Credit Ledger",
    "frappe.db",
    "checkpoint",
    "KSampler",
    "CUDA",
    "local model",
)


def unique(prefix: str) -> str:
    return f"{prefix} {uuid4().hex[:8]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def ensure_user(email: str):
    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
        user.enabled = 1
        user.user_type = "System User"
        user.save(ignore_permissions=True)
    else:
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Slow AI",
                "last_name": "Tool User",
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
                "roles": [{"role": "Desk User"}],
            }
        ).insert(ignore_permissions=True)
    roles = {row.role for row in user.get("roles", [])}
    if "Desk User" not in roles:
        user.append("roles", {"role": "Desk User"})
        user.save(ignore_permissions=True)
    update_password(email, "SlowAiTool!2345")
    return email


def create_project(owner: str):
    project = insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Public Tool Project"),
            "status": "Open",
        }
    )
    frappe.db.set_value("AI Project", project.name, "owner", owner)
    project.reload()
    return project


def text_tool_nodes(text: str = "Template prompt"):
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


def text_tool_edges():
    return [
        {
            "id": "edge_1",
            "source": "prompt_1",
            "source_port": "text",
            "target": "tool_output_1",
            "target_port": "text",
        }
    ]


def upload_tool_nodes(asset_name: str):
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
                "description": "Selected image",
                "schema": {"type": "string"},
            },
        },
    ]


def upload_tool_edges():
    return [
        {
            "id": "edge_1",
            "source": "asset_1",
            "source_port": "image",
            "target": "tool_output_1",
            "target_port": "image",
        }
    ]


def provider_tool_nodes(provider: str, model: str):
    return [
        {
            "id": "prompt_1",
            "type": "text_prompt",
            "label": "Prompt",
            "position": {"x": 96, "y": 128},
            "config": {"text": "Provider prompt"},
        },
        {
            "id": "provider_1",
            "type": "provider_text_to_image",
            "label": "Provider Image",
            "position": {"x": 376, "y": 128},
            "config": {"provider": provider, "model": model},
        },
        {
            "id": "output_1",
            "type": "export_output",
            "label": "Output",
            "position": {"x": 656, "y": 128},
            "config": {},
        },
    ]


def provider_tool_edges():
    return [
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


def save_template(template_name: str, status: str, nodes, edges):
    return frappe.call(
        "slow_ai.api.templates.save_template",
        template_name=template_name,
        status=status,
        category="Public Tool Test",
        description=f"{status} public tool fixture",
        nodes=json.dumps(nodes),
        edges=json.dumps(edges),
        layout=json.dumps({"nodes": [{"id": nodes[0]["id"], "x": 96, "y": 128}]}),
    )


class TestPublicToolPage(FrappeTestCase):
    def setUp(self):
        self.previous_user = frappe.session.user
        self.user = ensure_user(f"slow.ai.public.tool.{uuid4().hex[:8]}@example.test")

    def tearDown(self):
        frappe.set_user(self.previous_user)

    def test_public_tool_page_uses_only_safe_backend_apis(self):
        frappe.reload_doc("slow_ai", "page", "slow_ai_tools")
        page = frappe.get_doc("Page", "slow-ai-tools")
        page.load_assets()

        self.assertEqual(page.module, "Slow Ai")
        self.assertIn("frappe.pages[\"slow-ai-tools\"]", page.script)
        self.assertIn("frappe.templates[\"slow_ai_tools\"]", page.script)
        self.assertIn("Published Templates", page.script)
        self.assertIn("This workflow may call an external provider and spend credits.", page.script)
        self.assertIn("slow_ai.api.public_tools.list_templates", page.script)
        self.assertIn("slow_ai.api.public_tools.get_template", page.script)
        self.assertIn("slow_ai.api.public_tools.create_workflow_from_template", page.script)
        self.assertIn("slow_ai.api.workflows.save_workflow", page.script)
        self.assertIn("slow_ai.api.runs.start_run", page.script)
        self.assertIn("slow_ai.api.runs.get_run_status", page.script)
        self.assertIn("slow_ai.api.runs.get_history", page.script)
        self.assertIn("slow_ai.api.assets.upload", page.script)
        self.assertIn("slow_ai.api.assets.view", page.script)
        self.assertIn("slow_ai.api.billing.get_balance", page.script)
        self.assertIn("slow_ai.api.models.get_model_metadata", page.script)
        self.assertIn("assetNamesFromHistory", page.script)

        methods = set(re.findall(r"frappe\.call\(\s*[\"']([^\"']+)[\"']", page.script))
        self.assertTrue(methods)
        self.assertTrue(methods.issubset(ALLOWED_PUBLIC_TOOL_METHODS))
        for fragment in FORBIDDEN_PUBLIC_TOOL_FRAGMENTS:
            self.assertNotIn(fragment, page.script)

    def test_public_tool_apis_list_only_published_templates_and_reject_unpublished(self):
        published = save_template(unique("Published Tool"), "PUBLISHED", text_tool_nodes(), text_tool_edges())
        draft = save_template(unique("Draft Tool"), "DRAFT", text_tool_nodes(), text_tool_edges())
        archived = save_template(unique("Archived Tool"), "ARCHIVED", text_tool_nodes(), text_tool_edges())
        project = create_project(self.user)

        frappe.set_user(self.user)
        listed = frappe.call("slow_ai.api.public_tools.list_templates")
        loaded = frappe.call("slow_ai.api.public_tools.get_template", template=published["name"])
        created = frappe.call(
            "slow_ai.api.public_tools.create_workflow_from_template",
            template=published["name"],
            project=project.name,
            title="Normal User Public Tool Draft",
        )

        listed_names = {row["name"] for row in listed["templates"]}
        self.assertIn(published["name"], listed_names)
        self.assertNotIn(draft["name"], listed_names)
        self.assertNotIn(archived["name"], listed_names)
        self.assertEqual(loaded["status"], "PUBLISHED")
        self.assertTrue(frappe.db.exists("AI Workflow", created["name"]))
        self.assertEqual(frappe.db.get_value("AI Workflow", created["name"], "owner"), self.user)

        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.public_tools.get_template", template=draft["name"])
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.public_tools.create_workflow_from_template",
                template=archived["name"],
                project=project.name,
                title="Rejected Public Tool Draft",
            )

    def test_template_publishing_requires_system_manager(self):
        frappe.set_user(self.user)

        draft = frappe.call(
            "slow_ai.api.templates.save_template",
            template_name=unique("Normal User Draft Tool"),
            status="DRAFT",
            category="Public Tool Test",
            description="Normal user draft fixture",
            nodes=json.dumps(text_tool_nodes()),
            edges=json.dumps(text_tool_edges()),
            layout=json.dumps({"nodes": [{"id": "prompt_1", "x": 96, "y": 128}]}),
        )

        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.templates.save_template",
                template=draft["name"],
                template_name=draft["template_name"],
                status="PUBLISHED",
                category="Public Tool Test",
                description="Rejected publish fixture",
                nodes=json.dumps(draft["nodes"]),
                edges=json.dumps(draft["edges"]),
                layout=json.dumps(draft["layout"]),
            )

    def test_public_tool_run_persists_form_values_and_starts_through_run_api(self):
        template = save_template(unique("Runnable Public Tool"), "PUBLISHED", text_tool_nodes(), text_tool_edges())
        project = create_project(self.user)
        provider_jobs_before = frappe.db.count("AI Provider Job")

        frappe.set_user(self.user)
        draft = frappe.call(
            "slow_ai.api.public_tools.create_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Runnable Public Tool Draft",
        )
        draft["nodes"][0]["config"]["text"] = "Prompt entered on public tool page"
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
        status = frappe.call("slow_ai.api.runs.get_run_status", workflow_run=run["workflow_run"])

        self.assertEqual(saved["nodes"][0]["config"]["text"], "Prompt entered on public tool page")
        self.assertTrue(frappe.db.exists("AI Workflow Version", run["workflow_version"]))
        self.assertEqual(status["workflow_run"], run["workflow_run"])
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_jobs_before)

    def test_public_tool_provider_template_preflight_rejects_insufficient_balance_before_provider_job(self):
        provider = unique("public-tool-provider")
        model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": f"{provider}/paid-model",
                "model_name": "Public Tool Paid Model",
                "provider": provider,
                "status": "ENABLED",
                "node_type": "provider_text_to_image",
                "category": "provider",
                "modality": "TEXT_TO_IMAGE",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": "0.20"}),
            }
        )
        insert_doc(
            {
                "doctype": "AI Provider Account",
                "provider": provider,
                "account_label": unique("Public Tool Provider Account"),
                "api_key_secret": "public-tool-provider-secret",
                "is_default": 1,
                "status": "ACTIVE",
            }
        )
        template = save_template(
            unique("Paid Public Tool"),
            "PUBLISHED",
            provider_tool_nodes(provider, model.name),
            provider_tool_edges(),
        )
        project = create_project(self.user)
        provider_jobs_before = frappe.db.count("AI Provider Job")

        frappe.set_user(self.user)
        draft = frappe.call(
            "slow_ai.api.public_tools.create_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Paid Public Tool Draft",
        )

        with self.assertRaises(RunPreflightError):
            frappe.call("slow_ai.api.runs.start_run", workflow=draft["name"])

        self.assertEqual(frappe.db.count("AI Provider Job"), provider_jobs_before)
        self.assertFalse(frappe.db.exists("AI Workflow Run", {"workflow": draft["name"]}))

    def test_public_tool_upload_asset_output_preview_uses_history_and_asset_view(self):
        project = create_project(self.user)
        frappe.set_user(self.user)
        asset = frappe.call(
            "slow_ai.api.assets.upload",
            project=project.name,
            asset_type="IMAGE",
            url="https://example.invalid/public-tool-input.png",
            mime_type="image/png",
            metadata={"origin": "public_tool_test"},
        )

        frappe.set_user(self.previous_user)
        template = save_template(
            unique("Upload Public Tool"),
            "PUBLISHED",
            upload_tool_nodes(asset["name"]),
            upload_tool_edges(),
        )

        frappe.set_user(self.user)
        draft = frappe.call(
            "slow_ai.api.public_tools.create_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Upload Public Tool Draft",
        )
        draft["nodes"][0]["config"]["asset"] = asset["name"]
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
        run_workflow(run["workflow_run"])
        history = frappe.call("slow_ai.api.runs.get_history", workflow_run=run["workflow_run"])
        output_values = [node["output"] for node in history["node_runs"]]
        preview = frappe.call("slow_ai.api.assets.view", asset=asset["name"])

        self.assertTrue(any(asset["name"] in json.dumps(output, default=str) for output in output_values))
        self.assertEqual(preview["name"], asset["name"])
        self.assertEqual(preview["url"], "https://example.invalid/public-tool-input.png")

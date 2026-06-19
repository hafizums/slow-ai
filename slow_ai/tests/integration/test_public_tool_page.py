import json
import re
from pathlib import Path
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days
from frappe.utils import now_datetime
from frappe.utils.password import update_password

from slow_ai.domain.exceptions import RunPreflightError
from slow_ai.workers.run_workflow import run_workflow


ALLOWED_PUBLIC_TOOL_METHODS = {
    "slow_ai.api.public_tools.list_templates",
    "slow_ai.api.public_tools.get_template",
    "slow_ai.api.public_tools.prepare_workflow_from_template",
    "slow_ai.api.public_tools.list_my_runs",
    "slow_ai.api.public_tools.get_my_run",
    "slow_ai.api.public_tools.get_run_output_gallery",
    "slow_ai.api.public_tools.create_run_share",
    "slow_ai.api.public_tools.disable_run_share",
    "slow_ai.api.public_tools.get_shared_run",
    "slow_ai.api.runs.start_run",
    "slow_ai.api.assets.upload",
    "slow_ai.api.assets.view",
    "slow_ai.api.billing.get_balance",
    "slow_ai.api.models.get_model_metadata",
    "slow_ai.api.projects.list_members",
    "slow_ai.api.projects.add_member",
    "slow_ai.api.projects.update_member_role",
    "slow_ai.api.projects.disable_member",
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


def add_member(project: str, user: str, role: str):
    return insert_doc(
        {
            "doctype": "AI Project Member",
            "project": project,
            "user": user,
            "role": role,
            "status": "ACTIVE",
        }
    )


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


def create_text_tool_run(user: str, title: str = "Public Tool Run"):
    frappe.set_user("Administrator")
    template = save_template(unique("Run Library Template"), "PUBLISHED", text_tool_nodes(), text_tool_edges())
    project = create_project(user)
    frappe.set_user(user)
    draft = frappe.call(
        "slow_ai.api.public_tools.create_workflow_from_template",
        template=template["name"],
        project=project.name,
        title=title,
    )
    run = frappe.call("slow_ai.api.runs.start_run", workflow=draft["name"])
    return {"project": project, "workflow": draft, "run": run}


def create_shareable_asset_run(user: str, title: str = "Shareable Public Tool Run"):
    created = create_text_tool_run(user, title=title)
    run_workflow(created["run"]["workflow_run"])
    node_run = frappe.db.get_value(
        "AI Node Run",
        {"workflow_run": created["run"]["workflow_run"], "node_id": "tool_output_1"},
        "name",
    )
    asset = insert_doc(
        {
            "doctype": "AI Asset",
            "project": created["project"].name,
            "asset_type": "IMAGE",
            "url": "https://example.invalid/shared-public-output.png",
            "mime_type": "image/png",
            "source_workflow_run": created["run"]["workflow_run"],
            "source_node_run": node_run,
            "metadata_json": json.dumps({"origin": "tool-run-sharing-test"}),
        }
    )
    other_asset = insert_doc(
        {
            "doctype": "AI Asset",
            "project": created["project"].name,
            "asset_type": "IMAGE",
            "url": "https://example.invalid/shared-public-unselected-output.png",
            "mime_type": "image/png",
            "source_workflow_run": created["run"]["workflow_run"],
            "source_node_run": node_run,
            "metadata_json": json.dumps({"origin": "tool-run-sharing-unselected-test"}),
        }
    )
    return {**created, "asset": asset, "other_asset": other_asset}


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
        self.assertIn("slow_ai.api.public_tools.prepare_workflow_from_template", page.script)
        self.assertNotIn("slow_ai.api.public_tools.create_workflow_from_template", page.script)
        self.assertIn("slow_ai.api.public_tools.list_my_runs", page.script)
        self.assertIn("slow_ai.api.public_tools.get_my_run", page.script)
        self.assertIn("slow_ai.api.public_tools.get_run_output_gallery", page.script)
        self.assertIn("slow_ai.api.public_tools.create_run_share", page.script)
        self.assertIn("slow_ai.api.public_tools.disable_run_share", page.script)
        self.assertIn("Select output assets to include in the share link", page.script)
        self.assertNotIn("slow_ai.api.workflows.save_workflow", page.script)
        self.assertIn("slow_ai.api.runs.start_run", page.script)
        self.assertIn("slow_ai.api.assets.upload", page.script)
        self.assertIn("slow_ai.api.assets.view", page.script)
        self.assertIn("slow_ai.api.billing.get_balance", page.script)
        self.assertIn("slow_ai.api.models.get_model_metadata", page.script)
        self.assertIn("renderOutputGallery", page.script)

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
        saved = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Runnable Public Tool Draft",
            values={"prompt_1": {"text": "Prompt entered on public tool page"}},
        )
        run = frappe.call("slow_ai.api.runs.start_run", workflow=saved["name"])
        status = frappe.call("slow_ai.api.runs.get_run_status", workflow_run=run["workflow_run"])

        self.assertEqual(saved["nodes"][0]["config"]["text"], "Prompt entered on public tool page")
        self.assertTrue(frappe.db.exists("AI Workflow Version", run["workflow_version"]))
        self.assertEqual(status["workflow_run"], run["workflow_run"])
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_jobs_before)

    def test_run_library_scopes_normal_users_to_owned_project_runs(self):
        other_user = ensure_user(f"slow.ai.public.other.{uuid4().hex[:8]}@example.test")
        own = create_text_tool_run(self.user, title="Own Public Tool Run")
        other = create_text_tool_run(other_user, title="Other Public Tool Run")

        frappe.set_user(self.user)
        listed = frappe.call("slow_ai.api.public_tools.list_my_runs")
        listed_names = {row["workflow_run"] for row in listed["runs"]}

        self.assertIn(own["run"]["workflow_run"], listed_names)
        self.assertNotIn(other["run"]["workflow_run"], listed_names)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=other["run"]["workflow_run"])

    def test_run_library_system_manager_can_view_all_runs(self):
        other_user = ensure_user(f"slow.ai.public.other.{uuid4().hex[:8]}@example.test")
        own = create_text_tool_run(self.user, title="Own Public Tool Run")
        other = create_text_tool_run(other_user, title="Other Public Tool Run")

        frappe.set_user(self.previous_user)
        listed = frappe.call("slow_ai.api.public_tools.list_my_runs")
        listed_names = {row["workflow_run"] for row in listed["runs"]}

        self.assertIn(own["run"]["workflow_run"], listed_names)
        self.assertIn(other["run"]["workflow_run"], listed_names)
        detail = frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=other["run"]["workflow_run"])
        self.assertEqual(detail["run"]["workflow_run"], other["run"]["workflow_run"])

    def test_run_library_detail_returns_safe_history_and_asset_names_only(self):
        created = create_text_tool_run(self.user, title="Safe Public Tool Run")
        workflow_run = created["run"]["workflow_run"]
        node_run = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": workflow_run, "node_id": "tool_output_1"},
            "name",
        )
        secret = "raw-provider-secret-token"
        raw_provider_url = "https://provider.example.invalid/private-output.png"
        model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": "safe-provider/model",
                "model_name": "Safe Provider Model",
                "provider": "safe-provider",
                "status": "ENABLED",
                "node_type": "provider_text_to_image",
                "category": "provider",
                "modality": "TEXT_TO_IMAGE",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": "0.25"}),
            }
        )
        provider_job = insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run,
                "provider": "safe-provider",
                "model": model.name,
                "status": "FAILED",
                "request_json": json.dumps({"Authorization": f"Bearer {secret}"}),
                "response_json": json.dumps({"output": raw_provider_url, "api_key_secret": secret}),
                "raw_error_json": json.dumps({"message": f"Provider failed Authorization={secret}"}),
            }
        )
        timestamp = now_datetime()
        frappe.db.set_value(
            "AI Workflow Run",
            workflow_run,
            {
                "status": "FAILED",
                "started_at": timestamp,
                "completed_at": timestamp,
                "error_json": json.dumps({"message": f"Run failed Bearer {secret}"}),
            },
        )
        frappe.db.set_value(
            "AI Node Run",
            node_run,
            {
                "status": "FAILED",
                "provider_job": provider_job.name,
                "error_json": json.dumps({"message": f"Node failed token={secret}"}),
            },
        )
        asset = insert_doc(
            {
                "doctype": "AI Asset",
                "project": created["project"].name,
                "asset_type": "IMAGE",
                "url": "https://example.invalid/safe-library-output.png",
                "mime_type": "image/png",
                "source_workflow_run": workflow_run,
                "source_node_run": node_run,
                "source_provider_job": provider_job.name,
                "metadata_json": json.dumps({"origin": "run-library-test"}),
            }
        )
        insert_doc(
            {
                "doctype": "AI Credit Ledger",
                "project": created["project"].name,
                "workflow_run": workflow_run,
                "node_run": node_run,
                "provider_job": provider_job.name,
                "ledger_type": "DEBIT",
                "amount_usd": "0.25",
                "currency": "USD",
                "description": "Run library test debit",
            }
        )
        provider_jobs_before = frappe.db.count("AI Provider Job")

        frappe.set_user(self.user)
        detail = frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=workflow_run)
        listed = frappe.call("slow_ai.api.public_tools.list_my_runs", project=created["project"].name)
        preview = frappe.call("slow_ai.api.assets.view", asset=asset.name)
        payload = json.dumps(detail, default=str)

        self.assertIn(asset.name, {row["name"] for row in detail["assets"]})
        self.assertEqual(preview["url"], "https://example.invalid/safe-library-output.png")
        self.assertIn(workflow_run, {row["workflow_run"] for row in listed["runs"]})
        self.assertEqual(detail["cost_summary"]["debits_usd"], "0.25")
        self.assertEqual(detail["provider_summary"]["FAILED"], 1)
        self.assertIn("[redacted]", payload)
        self.assertNotIn(secret, payload)
        self.assertNotIn(raw_provider_url, payload)
        self.assertNotIn("provider_account", payload)
        self.assertNotIn("request_json", payload)
        self.assertNotIn("response_json", payload)
        self.assertNotIn("raw_error_json", payload)
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
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Paid Public Tool Draft",
            values={},
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
        saved = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Upload Public Tool Draft",
            values={"asset_1": {"asset": asset["name"]}},
        )
        run = frappe.call("slow_ai.api.runs.start_run", workflow=saved["name"])
        run_workflow(run["workflow_run"])
        history = frappe.call("slow_ai.api.runs.get_history", workflow_run=run["workflow_run"])
        output_values = [node["output"] for node in history["node_runs"]]
        preview = frappe.call("slow_ai.api.assets.view", asset=asset["name"])

        self.assertTrue(any(asset["name"] in json.dumps(output, default=str) for output in output_values))
        self.assertEqual(preview["name"], asset["name"])
        self.assertEqual(preview["url"], "https://example.invalid/public-tool-input.png")

    def test_run_output_gallery_returns_safe_grouped_assets_and_no_side_effects(self):
        created = create_shareable_asset_run(self.user, title="Gallery Safe Run")
        run_name = created["run"]["workflow_run"]
        node_run = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": run_name, "node_id": "tool_output_1"},
            "name",
        )
        secret = "gallery-secret-token"
        model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": unique("gallery-provider/model"),
                "model_name": "Gallery Provider Model",
                "provider": "gallery-provider",
                "status": "ENABLED",
                "node_type": "provider_text_to_image",
                "category": "provider",
                "modality": "TEXT_TO_IMAGE",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": "0.01"}),
            }
        )
        account = insert_doc(
            {
                "doctype": "AI Provider Account",
                "provider": "gallery-provider",
                "account_label": "gallery-provider-account-secret-name",
                "api_key_secret": secret,
                "status": "ACTIVE",
            }
        )
        provider_job = insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run,
                "provider": "gallery-provider",
                "model": model.name,
                "status": "SUCCEEDED",
                "provider_account": account.name,
                "request_json": json.dumps({"Authorization": f"Bearer {secret}"}),
                "response_json": json.dumps({"output": "https://provider.example.invalid/raw.png", "secret": secret}),
                "raw_error_json": json.dumps({"message": f"token={secret}"}),
            }
        )
        frappe.db.set_value("AI Asset", created["asset"].name, "source_provider_job", provider_job.name)
        counts_before = {
            "AI Provider Job": frappe.db.count("AI Provider Job"),
            "AI Asset": frappe.db.count("AI Asset"),
            "AI Credit Ledger": frappe.db.count("AI Credit Ledger"),
            "AI Workflow Version": frappe.db.count("AI Workflow Version"),
            "AI Workflow Run": frappe.db.count("AI Workflow Run"),
            "AI Node Run": frappe.db.count("AI Node Run"),
        }

        frappe.set_user(self.user)
        gallery = frappe.call("slow_ai.api.public_tools.get_run_output_gallery", workflow_run=run_name)
        encoded = json.dumps(gallery, default=str)

        self.assertEqual(gallery["run"]["workflow_run"], run_name)
        self.assertTrue(gallery["groups"])
        self.assertIn(created["asset"].name, {asset["name"] for asset in gallery["assets"]})
        self.assertIn(created["other_asset"].name, {asset["name"] for asset in gallery["assets"]})
        self.assertTrue(all("assets" in group for group in gallery["groups"]))
        self.assertIn("source_node_run", gallery["assets"][0])
        self.assertNotIn("gallery-provider-account-secret-name", encoded)
        self.assertNotIn(account.name, encoded)
        self.assertNotIn(secret, encoded)
        self.assertNotIn("request_json", encoded)
        self.assertNotIn("response_json", encoded)
        self.assertNotIn("raw_error_json", encoded)
        for doctype, count in counts_before.items():
            self.assertEqual(frappe.db.count(doctype), count, doctype)

    def test_run_output_gallery_respects_project_membership(self):
        created = create_shareable_asset_run(self.user, title="Gallery Membership Run")
        viewer = ensure_user(f"slow.ai.gallery.viewer.{uuid4().hex[:8]}@example.test")
        editor = ensure_user(f"slow.ai.gallery.editor.{uuid4().hex[:8]}@example.test")
        outsider = ensure_user(f"slow.ai.gallery.outsider.{uuid4().hex[:8]}@example.test")
        add_member(created["project"].name, viewer, "VIEWER")
        add_member(created["project"].name, editor, "EDITOR")

        frappe.set_user(viewer)
        viewer_gallery = frappe.call(
            "slow_ai.api.public_tools.get_run_output_gallery",
            workflow_run=created["run"]["workflow_run"],
        )
        frappe.set_user(editor)
        editor_gallery = frappe.call(
            "slow_ai.api.public_tools.get_run_output_gallery",
            workflow_run=created["run"]["workflow_run"],
        )
        frappe.set_user(outsider)
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.public_tools.get_run_output_gallery",
                workflow_run=created["run"]["workflow_run"],
            )

        self.assertEqual(viewer_gallery["run"]["workflow_run"], created["run"]["workflow_run"])
        self.assertEqual(editor_gallery["run"]["workflow_run"], created["run"]["workflow_run"])

    def test_run_output_gallery_empty_failed_run_returns_safe_empty_payload(self):
        created = create_text_tool_run(self.user, title="Gallery Empty Failed Run")
        workflow_run = created["run"]["workflow_run"]
        frappe.db.set_value(
            "AI Workflow Run",
            workflow_run,
            {
                "status": "FAILED",
                "error_json": json.dumps({"message": "Failed without outputs token=secret"}),
            },
        )

        frappe.set_user(self.user)
        gallery = frappe.call("slow_ai.api.public_tools.get_run_output_gallery", workflow_run=workflow_run)

        self.assertEqual(gallery["run"]["workflow_run"], workflow_run)
        self.assertEqual(gallery["run"]["status"], "FAILED")
        self.assertEqual(gallery["groups"], [])
        self.assertEqual(gallery["assets"], [])

    def test_user_can_create_share_with_selected_asset_and_guest_sees_only_selected_output(self):
        created = create_shareable_asset_run(self.user)
        counts_before = {
            "AI Tool Run Share": frappe.db.count("AI Tool Run Share"),
            "AI Provider Job": frappe.db.count("AI Provider Job"),
            "AI Asset": frappe.db.count("AI Asset"),
            "AI Credit Ledger": frappe.db.count("AI Credit Ledger"),
            "AI Workflow Version": frappe.db.count("AI Workflow Version"),
            "AI Workflow Run": frappe.db.count("AI Workflow Run"),
            "AI Node Run": frappe.db.count("AI Node Run"),
        }

        frappe.set_user(self.user)
        share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=created["run"]["workflow_run"],
            selected_assets=[created["asset"].name],
        )["share"]
        listed = frappe.call("slow_ai.api.public_tools.list_my_runs", project=created["project"].name)

        self.assertEqual(share["status"], "ACTIVE")
        self.assertTrue(share["share_token"])
        self.assertTrue(share["share_url"].startswith("/slow-ai/shared/"))
        self.assertEqual(share["selected_assets"], [created["asset"].name])
        self.assertEqual(frappe.db.count("AI Tool Run Share"), counts_before["AI Tool Run Share"] + 1)
        for doctype, count in counts_before.items():
            if doctype == "AI Tool Run Share":
                continue
            self.assertEqual(frappe.db.count(doctype), count, doctype)
        self.assertIn(
            share["share_token"],
            {row["share"]["share_token"] for row in listed["runs"] if row.get("share")},
        )
        counts_after_share = {
            "AI Provider Job": frappe.db.count("AI Provider Job"),
            "AI Asset": frappe.db.count("AI Asset"),
            "AI Credit Ledger": frappe.db.count("AI Credit Ledger"),
            "AI Workflow Version": frappe.db.count("AI Workflow Version"),
            "AI Workflow Run": frappe.db.count("AI Workflow Run"),
            "AI Node Run": frappe.db.count("AI Node Run"),
        }

        frappe.set_user("Guest")
        payload = frappe.call(
            "slow_ai.api.public_tools.get_shared_run",
            share_token=share["share_token"],
        )
        encoded = json.dumps(payload, default=str)

        self.assertEqual(payload["run"]["workflow_run"], created["run"]["workflow_run"])
        self.assertEqual(payload["run"]["status"], "SUCCEEDED")
        self.assertIn(created["asset"].name, {row["name"] for row in payload["assets"]})
        self.assertNotIn(created["other_asset"].name, {row["name"] for row in payload["assets"]})
        self.assertEqual({row["name"] for row in payload["output_gallery"]["assets"]}, {created["asset"].name})
        grouped_asset_names = {
            asset["name"]
            for group in payload["output_gallery"]["groups"]
            for asset in group.get("assets", [])
        }
        self.assertEqual(grouped_asset_names, {created["asset"].name})
        self.assertEqual(payload["assets"][0]["url"], "https://example.invalid/shared-public-output.png")
        self.assertIn("cost_summary", payload)
        self.assertNotIn("project", payload["run"])
        self.assertNotIn("project", payload["output_gallery"]["run"])
        self.assertNotIn("workflow", payload["output_gallery"]["run"])
        self.assertNotIn('"project"', encoded)
        self.assertNotIn('"workflow"', encoded)
        self.assertNotIn("draft_nodes_json", encoded)
        self.assertNotIn("draft_edges_json", encoded)
        self.assertNotIn('"nodes"', encoded)
        self.assertNotIn('"edges"', encoded)
        self.assertNotIn('"layout"', encoded)
        self.assertNotIn(created["project"].name, encoded)
        self.assertNotIn("provider_account", encoded)
        self.assertNotIn("request_json", encoded)
        self.assertNotIn("response_json", encoded)
        self.assertNotIn("raw_error_json", encoded)
        self.assertNotIn("api_key_secret", encoded)
        for doctype, count in counts_after_share.items():
            self.assertEqual(frappe.db.count(doctype), count, doctype)

    def test_share_rejects_unknown_other_run_and_empty_selected_assets(self):
        created = create_shareable_asset_run(self.user, title="Selected Shareable Run")
        other = create_shareable_asset_run(self.user, title="Other Selected Shareable Run")

        frappe.set_user(self.user)
        with self.assertRaises(frappe.ValidationError):
            frappe.call(
                "slow_ai.api.public_tools.create_run_share",
                workflow_run=created["run"]["workflow_run"],
                selected_assets=[],
            )
        with self.assertRaises(frappe.ValidationError):
            frappe.call(
                "slow_ai.api.public_tools.create_run_share",
                workflow_run=created["run"]["workflow_run"],
                selected_assets=["AI-ASSET-DOES-NOT-EXIST"],
            )
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.public_tools.create_run_share",
                workflow_run=created["run"]["workflow_run"],
                selected_assets=[other["asset"].name],
            )

    def test_share_permissions_and_system_manager_disable(self):
        other_user = ensure_user(f"slow.ai.share.other.{uuid4().hex[:8]}@example.test")
        other = create_shareable_asset_run(other_user, title="Other Shareable Run")

        frappe.set_user(self.user)
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.public_tools.create_run_share",
                workflow_run=other["run"]["workflow_run"],
            )

        frappe.set_user(self.previous_user)
        share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=other["run"]["workflow_run"],
            selected_assets=[other["asset"].name],
        )["share"]
        disabled = frappe.call(
            "slow_ai.api.public_tools.disable_run_share",
            share_token=share["share_token"],
        )["share"]

        self.assertEqual(disabled["status"], "DISABLED")
        self.assertIsNone(disabled["share_token"])

    def test_guest_cannot_read_disabled_or_expired_share(self):
        created = create_shareable_asset_run(self.user, title="Expiring Shareable Run")

        frappe.set_user(self.user)
        share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=created["run"]["workflow_run"],
            selected_assets=[created["asset"].name],
        )["share"]
        frappe.call("slow_ai.api.public_tools.disable_run_share", share_token=share["share_token"])

        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.public_tools.get_shared_run", share_token=share["share_token"])

        frappe.set_user(self.user)
        expiring = frappe.get_doc(
            {
                "doctype": "AI Tool Run Share",
                "workflow_run": created["run"]["workflow_run"],
                "project": created["project"].name,
                "share_token": f"expired-{uuid4().hex}",
                "status": "ACTIVE",
                "selected_assets_json": json.dumps([created["asset"].name]),
                "expires_at": add_days(now_datetime(), -1),
            }
        ).insert(ignore_permissions=True)

        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.public_tools.get_shared_run", share_token=expiring.share_token)

    def test_shared_page_client_uses_only_safe_read_api(self):
        page_path = Path(frappe.get_app_path("slow_ai")) / "www" / "slow-ai" / "shared.html"
        source = page_path.read_text(encoding="utf-8")

        self.assertIn("slow_ai.api.public_tools.get_shared_run", source)
        self.assertNotIn("slow_ai.api.runs.start_run", source)
        self.assertNotIn("slow_ai.api.public_tools.create_workflow_from_template", source)
        self.assertNotIn("slow_ai.api.workflows.save_workflow", source)
        for fragment in FORBIDDEN_PUBLIC_TOOL_FRAGMENTS:
            self.assertNotIn(fragment, source)

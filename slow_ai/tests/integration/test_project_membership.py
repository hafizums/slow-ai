import json
from decimal import Decimal
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import update_password

from slow_ai.domain.exceptions import RunPreflightError


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


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
                "last_name": "Project Member",
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
    if "System Manager" in roles:
        user.set("roles", [{"role": row.role} for row in user.get("roles", []) if row.role != "System Manager"])
        user.save(ignore_permissions=True)
    update_password(email, "SlowAiProject!2345")
    return email


def create_project(owner: str):
    project = insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Membership Project"),
            "status": "Open",
        }
    )
    frappe.db.set_value("AI Project", project.name, "owner", owner)
    project.reload()
    return project


def workflow_nodes(text: str = "membership prompt"):
    return [
        {"id": "prompt_1", "type": "text_prompt", "config": {"text": text}},
        {"id": "output_1", "type": "export_output", "config": {}},
    ]


def workflow_edges():
    return [
        {
            "id": "edge_1",
            "source": "prompt_1",
            "source_port": "text",
            "target": "output_1",
            "target_port": "text",
        }
    ]


def provider_nodes(provider: str, model: str, provider_account: str):
    return [
        {"id": "prompt_1", "type": "text_prompt", "config": {"text": "membership provider prompt"}},
        {
            "id": "provider_1",
            "type": "provider_text_to_image",
            "config": {"provider": provider, "model": model, "provider_account": provider_account},
        },
        {"id": "output_1", "type": "export_output", "config": {}},
    ]


def provider_edges():
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


def save_text_workflow(project: str, title: str = "Membership Workflow"):
    return frappe.call(
        "slow_ai.api.workflows.save_workflow",
        project=project,
        title=title,
        nodes=workflow_nodes(),
        edges=workflow_edges(),
        layout={},
    )


def create_successful_run_with_assets(project: str):
    workflow = insert_doc(
        {
            "doctype": "AI Workflow",
            "project": project,
            "title": unique("Membership Share Workflow"),
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(workflow_nodes()),
            "draft_edges_json": json.dumps(workflow_edges()),
            "layout_json": json.dumps({}),
        }
    )
    version = insert_doc(
        {
            "doctype": "AI Workflow Version",
            "workflow": workflow.name,
            "version_no": 1,
            "snapshot_hash": unique("membership-snapshot"),
            "nodes_json": workflow.draft_nodes_json,
            "edges_json": workflow.draft_edges_json,
            "layout_json": workflow.layout_json,
        }
    )
    run = insert_doc(
        {
            "doctype": "AI Workflow Run",
            "project": project,
            "workflow": workflow.name,
            "workflow_version": version.name,
            "status": "SUCCEEDED",
        }
    )
    node_run = insert_doc(
        {
            "doctype": "AI Node Run",
            "workflow_run": run.name,
            "node_id": "output_1",
            "node_type": "export_output",
            "status": "SUCCEEDED",
            "attempt_no": 1,
            "input_json": json.dumps({}),
            "config_json": json.dumps({}),
            "output_json": json.dumps({}),
        }
    )
    asset = insert_doc(
        {
            "doctype": "AI Asset",
            "project": project,
            "asset_type": "IMAGE",
            "url": "https://example.invalid/membership-output.png",
            "mime_type": "image/png",
            "source_workflow_run": run.name,
            "source_node_run": node_run.name,
            "metadata_json": json.dumps({"source": "project-membership-test"}),
        }
    )
    return run, asset


class TestProjectMembership(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"membership.owner.{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"membership.editor.{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"membership.viewer.{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"membership.billing.{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"membership.outsider.{uuid4().hex[:8]}@example.test")
        self.project = create_project(self.owner)

    def tearDown(self):
        frappe.set_user("Administrator")

    def add_member_as_owner(self, user: str, role: str):
        frappe.set_user(self.owner)
        return frappe.call("slow_ai.api.projects.add_member", project=self.project.name, user=user, role=role)

    def test_owner_and_system_manager_can_manage_project_members(self):
        member = self.add_member_as_owner(self.editor, "EDITOR")["member"]

        frappe.set_user(self.outsider)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.projects.add_member", project=self.project.name, user=self.viewer, role="VIEWER")

        frappe.set_user("Administrator")
        updated = frappe.call("slow_ai.api.projects.update_member_role", member=member["name"], role="VIEWER")
        disabled = frappe.call("slow_ai.api.projects.disable_member", member=member["name"])

        self.assertEqual(updated["member"]["role"], "VIEWER")
        self.assertEqual(disabled["member"]["status"], "DISABLED")

    def test_viewer_can_read_project_records_but_cannot_start_runs(self):
        frappe.set_user(self.owner)
        workflow = save_text_workflow(self.project.name)
        self.add_member_as_owner(self.viewer, "VIEWER")

        frappe.set_user(self.viewer)
        loaded = frappe.call("slow_ai.api.workflows.get_workflow", workflow=workflow["name"])
        version_count = frappe.db.count("AI Workflow Version", {"workflow": workflow["name"]})
        run_count = frappe.db.count("AI Workflow Run", {"workflow": workflow["name"]})

        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])

        self.assertEqual(loaded["name"], workflow["name"])
        self.assertEqual(frappe.db.count("AI Workflow Version", {"workflow": workflow["name"]}), version_count)
        self.assertEqual(frappe.db.count("AI Workflow Run", {"workflow": workflow["name"]}), run_count)

    def test_editor_can_save_and_start_non_provider_workflow(self):
        self.add_member_as_owner(self.editor, "EDITOR")

        frappe.set_user(self.editor)
        workflow = save_text_workflow(self.project.name, "Editor Runnable Workflow")
        result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])

        self.assertTrue(frappe.db.exists("AI Workflow", workflow["name"]))
        self.assertTrue(frappe.db.exists("AI Workflow Run", result["workflow_run"]))

    def test_billing_member_can_manage_billing_but_not_workflow_graph(self):
        self.add_member_as_owner(self.billing, "BILLING")

        frappe.set_user(self.billing)
        top_up = frappe.call(
            "slow_ai.api.billing.create_top_up",
            project=self.project.name,
            amount_usd="1.00",
            description="Membership billing credit",
        )
        ledger = frappe.call("slow_ai.api.billing.get_ledger", project=self.project.name)

        with self.assertRaises(frappe.PermissionError):
            save_text_workflow(self.project.name, "Billing Cannot Edit")

        self.assertEqual(Decimal(top_up["balance"]["balance_usd"]), Decimal("1.00"))
        self.assertEqual(Decimal(ledger["balance"]["balance_usd"]), Decimal("1.00"))

    def test_run_library_scopes_to_project_members_and_rejects_non_members(self):
        frappe.set_user(self.owner)
        workflow = save_text_workflow(self.project.name)
        result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])
        self.add_member_as_owner(self.viewer, "VIEWER")

        frappe.set_user(self.viewer)
        runs = frappe.call("slow_ai.api.public_tools.list_my_runs", project=self.project.name)
        detail = frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=result["workflow_run"])

        frappe.set_user(self.outsider)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=result["workflow_run"])

        self.assertIn(result["workflow_run"], {row["workflow_run"] for row in runs["runs"]})
        self.assertEqual(detail["run"]["workflow_run"], result["workflow_run"])

    def test_share_creation_requires_editor_or_owner_membership(self):
        frappe.set_user("Administrator")
        run, asset = create_successful_run_with_assets(self.project.name)
        self.add_member_as_owner(self.editor, "EDITOR")
        self.add_member_as_owner(self.viewer, "VIEWER")

        frappe.set_user(self.editor)
        share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=run.name,
            selected_assets=[asset.name],
        )["share"]

        frappe.set_user(self.viewer)
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.public_tools.create_run_share",
                workflow_run=run.name,
                selected_assets=[asset.name],
            )

        frappe.set_user(self.owner)
        disabled = frappe.call("slow_ai.api.public_tools.disable_run_share", share_token=share["share_token"])

        self.assertEqual(disabled["share"]["status"], "DISABLED")

    def test_provider_account_management_respects_billing_membership_and_hides_secret(self):
        self.add_member_as_owner(self.billing, "BILLING")
        provider = unique("membership-provider")
        secret = unique("membership-secret")
        provider_job_count = frappe.db.count("AI Provider Job")

        frappe.set_user(self.billing)
        created = frappe.call(
            "slow_ai.api.provider_accounts.create_account",
            provider=provider,
            account_label="Membership BYOK",
            api_key=secret,
            project=self.project.name,
            is_default=1,
        )
        listed = frappe.call("slow_ai.api.provider_accounts.list_accounts", provider=provider, project=self.project.name)
        fetched = frappe.call("slow_ai.api.provider_accounts.get_account", account=created["account"]["name"])

        frappe.set_user(self.viewer)
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.provider_accounts.create_account",
                provider=provider,
                account_label="Viewer BYOK",
                api_key=unique("viewer-secret"),
                project=self.project.name,
            )

        payload = json.dumps({"created": created, "listed": listed, "fetched": fetched}, default=str)
        self.assertNotIn(secret, payload)
        self.assertNotIn("api_key_secret", payload)
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)

    def test_insufficient_balance_preflight_for_editor_creates_no_side_effect_records(self):
        self.add_member_as_owner(self.editor, "EDITOR")
        provider = unique("membership-preflight-provider")
        model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": unique(f"{provider}/model"),
                "model_slug": unique(f"{provider}-slug"),
                "model_name": "Membership Preflight Model",
                "provider": provider,
                "status": "ENABLED",
                "node_type": "provider_text_to_image",
                "category": "provider",
                "modality": "TEXT_TO_IMAGE",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": "0.50", "currency": "USD"}),
            }
        )
        account = insert_doc(
            {
                "doctype": "AI Provider Account",
                "provider": provider,
                "account_label": "Membership Preflight Account",
                "project": self.project.name,
                "api_key_secret": unique("membership-preflight-secret"),
                "is_default": 1,
                "status": "ACTIVE",
            }
        )

        frappe.set_user(self.editor)
        workflow = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            project=self.project.name,
            title="Membership Insufficient Balance Workflow",
            nodes=provider_nodes(provider, model.name, account.name),
            edges=provider_edges(),
            layout={},
        )
        counts = {
            "AI Workflow Version": frappe.db.count("AI Workflow Version", {"workflow": workflow["name"]}),
            "AI Workflow Run": frappe.db.count("AI Workflow Run", {"workflow": workflow["name"]}),
            "AI Node Run": frappe.db.count("AI Node Run"),
            "AI Provider Job": frappe.db.count("AI Provider Job"),
        }

        with self.assertRaises(RunPreflightError):
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])

        self.assertEqual(frappe.db.count("AI Workflow Version", {"workflow": workflow["name"]}), counts["AI Workflow Version"])
        self.assertEqual(frappe.db.count("AI Workflow Run", {"workflow": workflow["name"]}), counts["AI Workflow Run"])
        self.assertEqual(frappe.db.count("AI Node Run"), counts["AI Node Run"])
        self.assertEqual(frappe.db.count("AI Provider Job"), counts["AI Provider Job"])

import json
from pathlib import Path
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.tests.integration.test_project_membership import ensure_user
from slow_ai.tests.integration.test_public_tool_page import add_member
from slow_ai.tests.integration.test_public_tool_page import save_template
from slow_ai.tests.integration.test_public_tool_page import text_tool_edges
from slow_ai.tests.integration.test_public_tool_page import text_tool_nodes
from slow_ai.tests.integration.test_public_tool_page import upload_tool_edges
from slow_ai.tests.integration.test_public_tool_page import upload_tool_nodes
from slow_ai.workers.run_workflow import run_workflow


SIDE_EFFECT_DOCTYPES = (
    "AI Workflow",
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
    "AI Workflow Template",
    "AI Workflow Template Version",
)

MUTATION_SNAPSHOT_FIELDS = {
    "AI Workflow": ["name", "project", "title", "draft_nodes_json", "modified"],
    "AI Workflow Version": ["name", "workflow", "snapshot_hash", "modified"],
    "AI Workflow Run": ["name", "workflow", "project", "status", "modified"],
    "AI Node Run": ["name", "workflow_run", "status", "output_json", "modified"],
    "AI Provider Job": ["name", "node_run", "status", "modified"],
    "AI Asset": [
        "name",
        "project",
        "asset_type",
        "url",
        "file",
        "source_workflow_run",
        "source_node_run",
        "source_provider_job",
        "metadata_json",
        "modified",
    ],
    "AI Credit Ledger": ["name", "project", "workflow_run", "ledger_type", "amount_usd", "modified"],
    "AI Tool Run Share": ["name", "workflow_run", "status", "selected_assets_json", "modified"],
    "AI Workflow Template": ["name", "status", "modified"],
    "AI Workflow Template Version": ["name", "template", "status", "modified"],
}

UNSAFE_FRAGMENTS = (
    "asset-access-provider-account",
    "ASSET_ACCESS_SECRET",
    "https://provider.example.invalid",
    "provider_account",
    "request_json",
    "response_json",
    "raw_error_json",
    "api_key",
    "Authorization",
    "Bearer",
    "draft_nodes_json",
    "draft_edges_json",
    "nodes_json",
    "edges_json",
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def _create_project(owner: str):
    project = _insert_doc(
        {
            "doctype": "AI Project",
            "project_name": _unique("Asset Access Project"),
            "status": "Open",
        }
    )
    frappe.db.set_value("AI Project", project.name, "owner", owner)
    project.reload()
    return project


def _record_counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def _mutation_snapshot() -> dict[str, list[dict]]:
    snapshot = {}
    for doctype, fields in MUTATION_SNAPSHOT_FIELDS.items():
        snapshot[doctype] = [dict(row) for row in frappe.get_all(doctype, fields=fields, order_by="name asc")]
    return json.loads(json.dumps(snapshot, default=str))


def _assert_no_side_effects(testcase: FrappeTestCase, before_counts: dict[str, int], before_snapshot: dict[str, list[dict]]):
    testcase.assertEqual(_record_counts(), before_counts)
    testcase.assertEqual(_mutation_snapshot(), before_snapshot)


def _assert_safe_payload(testcase: FrappeTestCase, payload):
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


def _upload_asset(project: str, *, url: str | None = None):
    return frappe.call(
        "slow_ai.api.assets.upload",
        project=project,
        asset_type="IMAGE",
        url=url or f"https://safe-assets.example.invalid/{uuid4().hex}.png",
        mime_type="image/png",
        metadata={
            "origin": "asset-access-test",
            "width": 128,
            "api_key": "ASSET_ACCESS_SECRET",
            "provider_url": "https://provider.example.invalid/raw",
            "nested": {"Authorization": "Bearer ASSET_ACCESS_SECRET"},
        },
    )


def _create_completed_run_with_assets(project: str):
    workflow = _insert_doc(
        {
            "doctype": "AI Workflow",
            "project": project,
            "title": _unique("Asset Gallery Workflow"),
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(text_tool_nodes("asset access output")),
            "draft_edges_json": json.dumps(text_tool_edges()),
            "layout_json": "{}",
        }
    )
    version = _insert_doc(
        {
            "doctype": "AI Workflow Version",
            "workflow": workflow.name,
            "version_no": 1,
            "snapshot_hash": _unique("asset-access-hash"),
            "nodes_json": workflow.draft_nodes_json,
            "edges_json": workflow.draft_edges_json,
            "layout_json": workflow.layout_json,
        }
    )
    run = _insert_doc(
        {
            "doctype": "AI Workflow Run",
            "project": project,
            "workflow": workflow.name,
            "workflow_version": version.name,
            "status": "SUCCEEDED",
        }
    )
    node_run = _insert_doc(
        {
            "doctype": "AI Node Run",
            "workflow_run": run.name,
            "node_id": "tool_output_1",
            "node_type": "tool_output",
            "status": "SUCCEEDED",
            "attempt_no": 1,
            "input_json": "{}",
            "config_json": "{}",
            "output_json": "{}",
        }
    )
    selected = _insert_doc(
        {
            "doctype": "AI Asset",
            "project": project,
            "asset_type": "IMAGE",
            "url": "https://safe-assets.example.invalid/selected.png",
            "mime_type": "image/png",
            "source_workflow_run": run.name,
            "source_node_run": node_run.name,
            "metadata_json": json.dumps({"origin": "selected", "api_key": "ASSET_ACCESS_SECRET"}),
        }
    )
    unselected = _insert_doc(
        {
            "doctype": "AI Asset",
            "project": project,
            "asset_type": "IMAGE",
            "url": "https://safe-assets.example.invalid/unselected.png",
            "mime_type": "image/png",
            "source_workflow_run": run.name,
            "source_node_run": node_run.name,
            "metadata_json": json.dumps({"origin": "unselected", "provider_url": "https://provider.example.invalid/raw"}),
        }
    )
    node_run.output_json = json.dumps({"selected": selected.name, "unselected": unselected.name})
    node_run.save(ignore_permissions=True)
    return workflow, run, selected, unselected


class TestAssetAccessMatrix(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"asset-access-owner-{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"asset-access-editor-{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"asset-access-viewer-{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"asset-access-billing-{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"asset-access-outsider-{uuid4().hex[:8]}@example.test")
        self.project = _create_project(self.owner)
        self.other_project = _create_project(self.outsider)
        add_member(self.project.name, self.editor, "EDITOR")
        add_member(self.project.name, self.viewer, "VIEWER")
        add_member(self.project.name, self.billing, "BILLING")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_owner_editor_and_system_manager_upload_one_asset_only_with_safe_payload(self):
        for user in (self.owner, self.editor, "Administrator"):
            before = _record_counts()
            frappe.set_user(user)
            payload = _upload_asset(self.project.name)
            self.assertEqual(frappe.db.count("AI Asset"), before["AI Asset"] + 1)
            for doctype, count in before.items():
                if doctype != "AI Asset":
                    self.assertEqual(frappe.db.count(doctype), count, doctype)
            self.assertEqual(payload["metadata"]["origin"], "asset-access-test")
            self.assertEqual(payload["metadata"]["width"], 128)
            _assert_safe_payload(self, payload)

    def test_view_roles_can_view_but_cannot_upload_and_nonmember_guest_are_denied(self):
        frappe.set_user(self.owner)
        asset = _upload_asset(self.project.name)
        before = _record_counts()
        before_snapshot = _mutation_snapshot()

        for user in (self.owner, self.editor, self.viewer, self.billing, "Administrator"):
            frappe.set_user(user)
            payload = frappe.call("slow_ai.api.assets.view", asset=asset["name"])
            self.assertEqual(payload["name"], asset["name"])
            _assert_safe_payload(self, payload)

        for user in (self.viewer, self.billing):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):
                _upload_asset(self.project.name)

        for user in (self.outsider, "Guest"):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):
                frappe.call("slow_ai.api.assets.view", asset=asset["name"])
            with self.assertRaises(frappe.PermissionError):
                _upload_asset(self.project.name)

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before, before_snapshot)

    def test_disabled_and_role_changed_members_immediately_affect_asset_access(self):
        frappe.set_user(self.owner)
        asset = _upload_asset(self.project.name)
        editor_member = frappe.db.get_value(
            "AI Project Member",
            {"project": self.project.name, "user": self.editor, "status": "ACTIVE"},
            "name",
        )

        frappe.set_user(self.editor)
        _upload_asset(self.project.name)

        frappe.set_user(self.owner)
        frappe.call("slow_ai.api.projects.update_member_role", member=editor_member, role="VIEWER")
        before = _record_counts()
        before_snapshot = _mutation_snapshot()

        frappe.set_user(self.editor)
        viewed = frappe.call("slow_ai.api.assets.view", asset=asset["name"])
        self.assertEqual(viewed["name"], asset["name"])
        with self.assertRaises(frappe.PermissionError):
            _upload_asset(self.project.name)

        frappe.set_user(self.owner)
        frappe.call("slow_ai.api.projects.disable_member", member=editor_member)

        frappe.set_user(self.editor)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.assets.view", asset=asset["name"])
        with self.assertRaises(frappe.PermissionError):
            _upload_asset(self.project.name)

        frappe.set_user("Administrator")
        self.assertEqual(_record_counts(), before)
        self.assertEqual(_mutation_snapshot(), before_snapshot)

    def test_gallery_and_shared_run_reads_are_selected_only_safe_and_side_effect_free(self):
        _, run, selected, unselected = _create_completed_run_with_assets(self.project.name)

        frappe.set_user(self.owner)
        share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=run.name,
            selected_assets=[selected.name],
        )["share"]
        before = _record_counts()
        before_snapshot = _mutation_snapshot()

        for user in (self.owner, self.editor, self.viewer, self.billing, "Administrator"):
            frappe.set_user(user)
            gallery = frappe.call("slow_ai.api.public_tools.get_run_output_gallery", workflow_run=run.name)
            self.assertIn(selected.name, {row["name"] for row in gallery["assets"]})
            self.assertIn(unselected.name, {row["name"] for row in gallery["assets"]})
            _assert_safe_payload(self, gallery)

        frappe.set_user("Guest")
        shared = frappe.call("slow_ai.api.public_tools.get_shared_run", share_token=share["share_token"])
        self.assertEqual({row["name"] for row in shared["assets"]}, {selected.name})
        self.assertEqual({row["name"] for row in shared["output_gallery"]["assets"]}, {selected.name})
        grouped = {asset["name"] for group in shared["output_gallery"]["groups"] for asset in group.get("assets", [])}
        self.assertEqual(grouped, {selected.name})
        self.assertNotIn(unselected.name, json.dumps(shared, default=str))
        _assert_safe_payload(self, shared)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.assets.view", asset=selected.name)

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before, before_snapshot)

    def test_public_tool_asset_inputs_and_rerun_updates_reject_inaccessible_assets(self):
        frappe.set_user(self.owner)
        allowed_asset = _upload_asset(self.project.name, url="https://safe-assets.example.invalid/allowed.png")
        frappe.set_user(self.outsider)
        inaccessible_asset = _upload_asset(
            self.other_project.name,
            url="https://safe-assets.example.invalid/inaccessible.png",
        )

        frappe.set_user("Administrator")
        template = save_template(
            _unique("Asset Access Upload Template"),
            "PUBLISHED",
            upload_tool_nodes(allowed_asset["name"]),
            upload_tool_edges(),
            [
                {
                    "id": "asset",
                    "label": "Asset",
                    "input_type": "IMAGE_ASSET",
                    "target_node_id": "asset_1",
                    "target_config_field": "asset",
                    "required": True,
                }
            ],
        )

        before_denied = _record_counts()
        before_snapshot = _mutation_snapshot()
        frappe.set_user(self.owner)
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.public_tools.prepare_workflow_from_template",
                template=template["name"],
                project=self.project.name,
                title="Denied Inaccessible Asset Draft",
                values={"asset": inaccessible_asset["name"]},
            )
        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_denied, before_snapshot)

        frappe.set_user(self.owner)
        draft = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=self.project.name,
            title="Allowed Asset Draft",
            values={"asset": allowed_asset["name"]},
        )
        run = frappe.call("slow_ai.api.runs.start_run", workflow=draft["name"])
        run_workflow(run["workflow_run"])
        rerun = frappe.call("slow_ai.api.public_tools.prepare_rerun_from_run", workflow_run=run["workflow_run"])

        before_update = _record_counts()
        before_update_snapshot = _mutation_snapshot()
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.public_tools.update_rerun_draft_values",
                workflow=rerun["workflow"]["name"],
                values={"asset": inaccessible_asset["name"]},
            )

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_update, before_update_snapshot)

    def test_asset_frontend_clients_use_safe_backend_apis_only(self):
        app_path = Path(frappe.get_app_path("slow_ai"))
        canvas = (app_path / "slow_ai/page/slow_ai_canvas/slow_ai_canvas.js").read_text()
        tools = (app_path / "slow_ai/page/slow_ai_tools/slow_ai_tools.js").read_text()
        shared = (app_path / "www/slow-ai/shared.html").read_text()

        self.assertIn("slow_ai.api.assets.upload", tools)
        self.assertIn("slow_ai.api.assets.view", canvas + tools)
        self.assertIn("slow_ai.api.public_tools.get_shared_run", shared)
        self.assertNotIn("slow_ai.api.assets.view", shared)
        forbidden = (
            "ProviderAdapter",
            "ProviderRegistry",
            "api.wavespeed.ai",
            "api.replicate.com",
            "frappe.db",
            "frappe.enqueue",
            "request_json",
            "response_json",
            "raw_error_json",
            "api_key_secret",
            "Authorization: Bearer",
        )
        for fragment in forbidden:
            self.assertNotIn(fragment, canvas, fragment)
            self.assertNotIn(fragment, tools, fragment)
            self.assertNotIn(fragment, shared, fragment)

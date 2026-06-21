import json
from pathlib import Path
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.domain.exceptions import GraphValidationError
from slow_ai.tests.integration.test_project_membership import ensure_user
from slow_ai.tests.integration.test_project_membership import workflow_edges
from slow_ai.tests.integration.test_project_membership import workflow_nodes
from slow_ai.tests.integration.test_public_tool_page import add_member
from slow_ai.tests.integration.test_public_tool_page import save_template
from slow_ai.tests.integration.test_public_tool_page import text_tool_edges
from slow_ai.tests.integration.test_public_tool_page import text_tool_input_schema
from slow_ai.tests.integration.test_public_tool_page import text_tool_nodes
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
    "AI Workflow": [
        "name",
        "project",
        "title",
        "status",
        "draft_nodes_json",
        "draft_edges_json",
        "layout_json",
        "source_template",
        "source_template_version",
        "is_temporary_tool_draft",
        "tool_draft_type",
        "modified",
    ],
    "AI Workflow Version": ["name", "workflow", "snapshot_hash", "modified"],
    "AI Workflow Run": ["name", "workflow", "project", "status", "modified"],
    "AI Node Run": ["name", "workflow_run", "status", "modified"],
    "AI Provider Job": ["name", "node_run", "status", "modified"],
    "AI Asset": ["name", "project", "source_workflow_run", "metadata_json", "modified"],
    "AI Credit Ledger": ["name", "project", "workflow_run", "ledger_type", "amount_usd", "modified"],
    "AI Tool Run Share": ["name", "workflow_run", "status", "modified"],
    "AI Workflow Template": ["name", "status", "modified"],
    "AI Workflow Template Version": ["name", "template", "status", "modified"],
}

UNSAFE_FRAGMENTS = (
    "workflow-draft-provider-account",
    "WORKFLOW_DRAFT_SECRET",
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
            "project_name": _unique("Workflow Access Project"),
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


def _save_workflow(project: str, *, title: str = "Workflow Access Draft", nodes=None, workflow: str | None = None):
    kwargs = {
        "project": project,
        "title": title,
        "nodes": nodes or workflow_nodes("workflow access prompt"),
        "edges": workflow_edges(),
        "layout": {"nodes": [{"id": "prompt_1", "x": 10, "y": 20}]},
    }
    if workflow:
        kwargs["workflow"] = workflow
    return frappe.call("slow_ai.api.workflows.save_workflow", **kwargs)


def _unsafe_nodes():
    nodes = workflow_nodes("workflow access unsafe")
    nodes[0]["config"].update(
        {
            "api_key": "WORKFLOW_DRAFT_SECRET",
            "request_json": {"Authorization": "Bearer WORKFLOW_DRAFT_SECRET"},
            "raw_error_json": {"url": "https://provider.example.invalid/raw"},
        }
    )
    return nodes


class TestWorkflowDraftAccessMatrix(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"workflow-access-owner-{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"workflow-access-editor-{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"workflow-access-viewer-{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"workflow-access-billing-{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"workflow-access-outsider-{uuid4().hex[:8]}@example.test")
        self.project = _create_project(self.owner)
        add_member(self.project.name, self.editor, "EDITOR")
        add_member(self.project.name, self.viewer, "VIEWER")
        add_member(self.project.name, self.billing, "BILLING")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_owner_editor_and_system_manager_can_create_edit_and_read_drafts(self):
        before = _record_counts()

        frappe.set_user(self.owner)
        owner_workflow = _save_workflow(self.project.name, title="Owner Draft")
        _assert_safe_payload(self, owner_workflow)
        self.assertEqual(frappe.db.count("AI Workflow"), before["AI Workflow"] + 1)
        for doctype, count in before.items():
            if doctype != "AI Workflow":
                self.assertEqual(frappe.db.count(doctype), count, doctype)

        counts_after_create = _record_counts()
        frappe.set_user(self.editor)
        edited = _save_workflow(
            self.project.name,
            workflow=owner_workflow["name"],
            title="Editor Updated Draft",
        )
        _assert_safe_payload(self, edited)
        self.assertEqual(_record_counts(), counts_after_create)
        self.assertEqual(frappe.db.get_value("AI Workflow", owner_workflow["name"], "title"), "Editor Updated Draft")

        frappe.set_user("Administrator")
        admin_workflow = _save_workflow(self.project.name, title="Admin Draft")
        self.assertEqual(frappe.db.count("AI Workflow"), counts_after_create["AI Workflow"] + 1)
        _assert_safe_payload(self, admin_workflow)

        before_reads = _record_counts()
        before_snapshot = _mutation_snapshot()
        for user in (self.owner, self.editor, self.viewer, self.billing, "Administrator"):
            frappe.set_user(user)
            payload = frappe.call("slow_ai.api.workflows.get_workflow", workflow=owner_workflow["name"])
            self.assertEqual(payload["name"], owner_workflow["name"])
            _assert_safe_payload(self, payload)

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_reads, before_snapshot)

    def test_viewer_billing_nonmember_and_guest_cannot_mutate_or_read_beyond_policy(self):
        frappe.set_user(self.owner)
        workflow = _save_workflow(self.project.name)
        before = _record_counts()
        before_snapshot = _mutation_snapshot()

        for user in (self.viewer, self.billing, self.outsider, "Guest"):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError, msg=f"{user} unexpectedly created draft"):
                _save_workflow(self.project.name, title=f"{user} Denied Draft")
            with self.assertRaises(frappe.PermissionError, msg=f"{user} unexpectedly edited draft"):
                _save_workflow(self.project.name, workflow=workflow["name"], title=f"{user} Denied Edit")

        for user in (self.viewer, self.billing):
            frappe.set_user(user)
            payload = frappe.call("slow_ai.api.workflows.get_workflow", workflow=workflow["name"])
            self.assertEqual(payload["name"], workflow["name"])
            _assert_safe_payload(self, payload)

        for user in (self.outsider, "Guest"):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError, msg=f"{user} unexpectedly read draft"):
                frappe.call("slow_ai.api.workflows.get_workflow", workflow=workflow["name"])

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before, before_snapshot)

    def test_disabled_and_role_changed_members_immediately_affect_workflow_draft_access(self):
        frappe.set_user(self.owner)
        workflow = _save_workflow(self.project.name)
        editor_member = frappe.db.get_value(
            "AI Project Member",
            {"project": self.project.name, "user": self.editor, "status": "ACTIVE"},
            "name",
        )

        frappe.set_user(self.editor)
        _save_workflow(self.project.name, workflow=workflow["name"], title="Editor Can Edit")

        frappe.set_user(self.owner)
        frappe.call("slow_ai.api.projects.update_member_role", member=editor_member, role="VIEWER")
        before = _record_counts()
        before_snapshot = _mutation_snapshot()

        frappe.set_user(self.editor)
        loaded = frappe.call("slow_ai.api.workflows.get_workflow", workflow=workflow["name"])
        self.assertEqual(loaded["name"], workflow["name"])
        with self.assertRaises(frappe.PermissionError):
            _save_workflow(self.project.name, workflow=workflow["name"], title="Viewer Cannot Edit")

        frappe.set_user(self.owner)
        frappe.call("slow_ai.api.projects.disable_member", member=editor_member)

        frappe.set_user(self.editor)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.workflows.get_workflow", workflow=workflow["name"])
        with self.assertRaises(frappe.PermissionError):
            _save_workflow(self.project.name, workflow=workflow["name"], title="Disabled Cannot Edit")

        frappe.set_user("Administrator")
        after_counts = _record_counts()
        after_snapshot = _mutation_snapshot()
        self.assertEqual(after_counts, before)
        # Membership changes are outside the guarded workflow/execution doctypes.
        self.assertEqual(after_snapshot, before_snapshot)

    def test_workflow_save_rejects_unsafe_config_and_read_redacts_persisted_provider_account(self):
        before = _record_counts()
        before_snapshot = _mutation_snapshot()

        frappe.set_user(self.owner)
        with self.assertRaises(GraphValidationError):
            _save_workflow(self.project.name, title="Unsafe Draft", nodes=_unsafe_nodes())

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before, before_snapshot)

        raw_nodes = workflow_nodes("workflow access provider account")
        raw_nodes[0]["config"]["provider_account"] = "workflow-draft-provider-account"
        raw_nodes[0]["config"]["notes"] = "safe visible note"
        raw_workflow = _insert_doc(
            {
                "doctype": "AI Workflow",
                "project": self.project.name,
                "title": "Raw Provider Account Draft",
                "status": "DRAFT",
                "draft_nodes_json": json.dumps(raw_nodes),
                "draft_edges_json": json.dumps(workflow_edges()),
                "layout_json": "{}",
            }
        )
        read_counts = _record_counts()
        read_snapshot = _mutation_snapshot()

        frappe.set_user(self.owner)
        loaded = frappe.call("slow_ai.api.workflows.get_workflow", workflow=raw_workflow.name)
        self.assertEqual(loaded["nodes"][0]["config"]["notes"], "safe visible note")
        _assert_safe_payload(self, loaded)

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, read_counts, read_snapshot)

    def test_public_tool_prepare_and_rerun_drafts_follow_project_access_without_execution_side_effects(self):
        frappe.set_user("Administrator")
        template = save_template(
            _unique("Workflow Access Template"),
            "PUBLISHED",
            text_tool_nodes("public workflow access prompt", style="natural", steps=4),
            text_tool_edges(),
            text_tool_input_schema(),
        )

        for denied_user in (self.viewer, self.billing, self.outsider, "Guest"):
            before = _record_counts()
            before_snapshot = _mutation_snapshot()
            frappe.set_user(denied_user)
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "slow_ai.api.public_tools.prepare_workflow_from_template",
                    template=template["name"],
                    project=self.project.name,
                    title="Denied Public Tool Draft",
                    values={"prompt": "Denied"},
                )
            frappe.set_user("Administrator")
            _assert_no_side_effects(self, before, before_snapshot)

        frappe.set_user(self.editor)
        before_prepare = _record_counts()
        prepared = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=self.project.name,
            title="Prepared Public Tool Draft",
            values={"prompt": "Prepared prompt", "style": "studio", "steps": 6},
        )
        self.assertEqual(frappe.db.count("AI Workflow"), before_prepare["AI Workflow"] + 1)
        for doctype, count in before_prepare.items():
            if doctype != "AI Workflow":
                self.assertEqual(frappe.db.count(doctype), count, doctype)
        _assert_safe_payload(self, prepared)

        run = frappe.call("slow_ai.api.runs.start_run", workflow=prepared["name"])
        run_workflow(run["workflow_run"])

        for denied_user in (self.viewer, self.billing, self.outsider, "Guest"):
            before = _record_counts()
            before_snapshot = _mutation_snapshot()
            frappe.set_user(denied_user)
            with self.assertRaises(frappe.PermissionError):
                frappe.call("slow_ai.api.public_tools.prepare_rerun_from_run", workflow_run=run["workflow_run"])
            frappe.set_user("Administrator")
            _assert_no_side_effects(self, before, before_snapshot)

        frappe.set_user(self.editor)
        before_rerun = _record_counts()
        rerun = frappe.call("slow_ai.api.public_tools.prepare_rerun_from_run", workflow_run=run["workflow_run"])
        self.assertEqual(frappe.db.count("AI Workflow"), before_rerun["AI Workflow"] + 1)
        for doctype, count in before_rerun.items():
            if doctype != "AI Workflow":
                self.assertEqual(frappe.db.count(doctype), count, doctype)
        _assert_safe_payload(self, rerun)

    def test_canvas_workflow_client_uses_safe_backend_apis_only(self):
        source = (Path(frappe.get_app_path("slow_ai")) / "slow_ai/page/slow_ai_canvas/slow_ai_canvas.js").read_text()

        self.assertIn("slow_ai.api.workflows.save_workflow", source)
        self.assertIn("slow_ai.api.workflows.get_workflow", source)
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
            self.assertNotIn(fragment, source, fragment)

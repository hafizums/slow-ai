import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.tests.integration.test_project_membership import ensure_user
from slow_ai.tests.integration.test_public_tool_page import add_member
from slow_ai.tests.integration.test_public_tool_page import create_project
from slow_ai.tests.integration.test_public_tool_page import create_shareable_asset_run
from slow_ai.tests.integration.test_public_tool_page import create_text_tool_run
from slow_ai.tests.integration.test_public_tool_page import insert_doc
from slow_ai.tests.integration.test_public_tool_page import save_template
from slow_ai.tests.integration.test_public_tool_page import text_tool_edges
from slow_ai.tests.integration.test_public_tool_page import text_tool_input_schema
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
)

MUTATION_SNAPSHOT_FIELDS = {
    "AI Workflow": ["name", "draft_nodes_json", "draft_edges_json", "layout_json", "modified"],
    "AI Workflow Run": ["name", "status", "is_archived", "archived_by", "archived_at", "error_json", "modified"],
    "AI Node Run": ["name", "workflow_run", "status", "provider_job", "error_json", "modified"],
    "AI Provider Job": ["name", "node_run", "status", "raw_error_json", "modified"],
    "AI Asset": ["name", "project", "source_workflow_run", "source_node_run", "source_provider_job", "modified"],
    "AI Credit Ledger": ["name", "workflow_run", "node_run", "provider_job", "ledger_type", "amount_usd", "modified"],
    "AI Tool Run Share": ["name", "workflow_run", "status", "selected_assets_json", "expires_at", "modified"],
}

UNSAFE_FRAGMENTS = (
    "write-action-provider-account-label",
    "WRITE_ACTION_SECRET",
    "sk_write_action_should_not_leak",
    "https://provider.example.invalid",
    "request_json",
    "response_json",
    "raw_error_json",
    "api_key",
    "Authorization",
    "Bearer",
    "Traceback",
    "stack trace",
)


def _unique(prefix: str) -> str:
    return f"{prefix} {uuid4().hex[:8]}"


def _counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def _snapshot() -> dict[str, list[dict]]:
    rows = {}
    for doctype, fields in MUTATION_SNAPSHOT_FIELDS.items():
        rows[doctype] = [dict(row) for row in frappe.get_all(doctype, fields=fields, order_by="name asc")]
    return json.loads(json.dumps(rows, default=str))


def _assert_counts_delta(testcase: FrappeTestCase, before: dict[str, int], expected_delta: dict[str, int]):
    after = _counts()
    for doctype in SIDE_EFFECT_DOCTYPES:
        testcase.assertEqual(after[doctype], before[doctype] + expected_delta.get(doctype, 0), doctype)


def _assert_no_side_effects(testcase: FrappeTestCase, before_counts: dict[str, int], before_snapshot: dict[str, list[dict]]):
    testcase.assertEqual(_counts(), before_counts)
    testcase.assertEqual(_snapshot(), before_snapshot)


def _assert_safe_payload(testcase: FrappeTestCase, payload):
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


def _assert_safe_exception(testcase: FrappeTestCase, exc: BaseException):
    encoded = str(exc)
    for fragment in (
        "write-action-provider-account-label",
        "WRITE_ACTION_SECRET",
        "sk_write_action_should_not_leak",
        "https://provider.example.invalid",
        "request_json",
        "response_json",
        "raw_error_json",
        "Authorization",
        "Bearer",
        "Traceback",
        "stack trace",
    ):
        testcase.assertNotIn(fragment, encoded, fragment)


def _save_text_workflow(project: str, title: str):
    return frappe.call(
        "slow_ai.api.workflows.save_workflow",
        project=project,
        title=title,
        nodes=text_tool_nodes(_unique("write action prompt")),
        edges=text_tool_edges(),
        layout={},
    )


class TestRunWriteActionAccessMatrix(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"run-write-owner-{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"run-write-editor-{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"run-write-viewer-{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"run-write-billing-{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"run-write-outsider-{uuid4().hex[:8]}@example.test")

    def tearDown(self):
        frappe.set_user("Administrator")

    def _new_project_with_members(self):
        project = create_project(self.owner)
        add_member(project.name, self.editor, "EDITOR")
        add_member(project.name, self.viewer, "VIEWER")
        add_member(project.name, self.billing, "BILLING")
        return project

    def _new_shareable_run_with_members(self, title: str):
        created = create_shareable_asset_run(self.owner, title=title)
        add_member(created["project"].name, self.editor, "EDITOR")
        add_member(created["project"].name, self.viewer, "VIEWER")
        add_member(created["project"].name, self.billing, "BILLING")
        return created

    def _new_text_run_with_members(self, title: str):
        created = create_text_tool_run(self.owner, title=title)
        add_member(created["project"].name, self.editor, "EDITOR")
        add_member(created["project"].name, self.viewer, "VIEWER")
        add_member(created["project"].name, self.billing, "BILLING")
        return created

    def test_start_run_access_matrix_and_side_effects(self):
        project = self._new_project_with_members()
        frappe.set_user(self.owner)
        denied_workflow = _save_text_workflow(project.name, "Denied Start Matrix Workflow")
        before_counts = _counts()
        before_snapshot = _snapshot()

        for user in (self.viewer, self.billing, self.outsider, "Guest"):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError) as exc:
                frappe.call("slow_ai.api.runs.start_run", workflow=denied_workflow["name"])
            _assert_safe_exception(self, exc.exception)

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_counts, before_snapshot)

        for user in (self.owner, self.editor, "Administrator"):
            if user == "Administrator":
                frappe.set_user(self.owner)
                workflow = _save_text_workflow(project.name, f"Admin Start Matrix Workflow {uuid4().hex[:4]}")
            else:
                frappe.set_user(user)
                workflow = _save_text_workflow(project.name, f"{user} Start Matrix Workflow")
            before = _counts()
            frappe.set_user(user)
            result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])

            _assert_safe_payload(self, result)
            self.assertTrue(result["workflow_version"])
            self.assertTrue(result["workflow_run"])
            self.assertEqual(len(result["node_runs"]), 2)
            self.assertIn("queue_job_id", result)
            _assert_counts_delta(
                self,
                before,
                {
                    "AI Workflow Version": 1,
                    "AI Workflow Run": 1,
                    "AI Node Run": 2,
                },
            )

    def test_cancel_archive_share_and_disable_access_matrix(self):
        cancellable = self._new_text_run_with_members("Write Matrix Cancellable Run")
        for user in (self.viewer, self.billing, self.outsider, "Guest"):
            before_counts = _counts()
            before_snapshot = _snapshot()
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError) as exc:
                frappe.call("slow_ai.api.public_tools.cancel_my_run", workflow_run=cancellable["run"]["workflow_run"])
            _assert_safe_exception(self, exc.exception)
            frappe.set_user("Administrator")
            _assert_no_side_effects(self, before_counts, before_snapshot)

        before_cancel = _counts()
        frappe.set_user(self.editor)
        cancelled = frappe.call("slow_ai.api.public_tools.cancel_my_run", workflow_run=cancellable["run"]["workflow_run"])
        _assert_safe_payload(self, cancelled)
        self.assertEqual(cancelled["run"]["status"], "CANCELLED")
        self.assertEqual(cancelled["run"]["error"], "Run cancelled by user.")
        _assert_counts_delta(self, before_cancel, {})

        frappe.set_user(self.owner)
        with self.assertRaises(frappe.ValidationError):
            frappe.call("slow_ai.api.public_tools.cancel_my_run", workflow_run=cancellable["run"]["workflow_run"])

        active_for_archive = self._new_text_run_with_members("Write Matrix Active Archive Rejection")
        before_active_archive = _counts()
        before_active_archive_snapshot = _snapshot()
        frappe.set_user(self.owner)
        with self.assertRaises(frappe.ValidationError):
            frappe.call("slow_ai.api.public_tools.archive_my_run", workflow_run=active_for_archive["run"]["workflow_run"])
        _assert_no_side_effects(self, before_active_archive, before_active_archive_snapshot)

        archive_target = self._new_text_run_with_members("Write Matrix Archive Target")
        run_workflow(archive_target["run"]["workflow_run"])
        for user in (self.viewer, self.billing, self.outsider, "Guest"):
            before_counts = _counts()
            before_snapshot = _snapshot()
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError) as exc:
                frappe.call("slow_ai.api.public_tools.archive_my_run", workflow_run=archive_target["run"]["workflow_run"])
            _assert_safe_exception(self, exc.exception)
            frappe.set_user("Administrator")
            _assert_no_side_effects(self, before_counts, before_snapshot)

        before_archive = _counts()
        frappe.set_user(self.owner)
        archived = frappe.call("slow_ai.api.public_tools.archive_my_run", workflow_run=archive_target["run"]["workflow_run"])
        _assert_safe_payload(self, archived)
        self.assertEqual(archived["run"]["is_archived"], 1)
        self.assertEqual(archived["run"]["archived_by"], self.owner)
        _assert_counts_delta(self, before_archive, {})

        share_target = self._new_shareable_run_with_members("Write Matrix Share Target")
        active_share_rejection = self._new_text_run_with_members("Write Matrix Active Share Rejection")
        before_active_share = _counts()
        before_active_share_snapshot = _snapshot()
        frappe.set_user(self.owner)
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.public_tools.create_run_share",
                workflow_run=active_share_rejection["run"]["workflow_run"],
                selected_assets=[share_target["asset"].name],
            )
        _assert_no_side_effects(self, before_active_share, before_active_share_snapshot)

        for user in (self.viewer, self.billing, self.outsider, "Guest"):
            before_counts = _counts()
            before_snapshot = _snapshot()
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError) as exc:
                frappe.call(
                    "slow_ai.api.public_tools.create_run_share",
                    workflow_run=share_target["run"]["workflow_run"],
                    selected_assets=[share_target["asset"].name],
                )
            _assert_safe_exception(self, exc.exception)
            frappe.set_user("Administrator")
            _assert_no_side_effects(self, before_counts, before_snapshot)

        before_share = _counts()
        frappe.set_user(self.editor)
        share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=share_target["run"]["workflow_run"],
            selected_assets=[share_target["asset"].name],
        )
        _assert_safe_payload(self, share)
        self.assertEqual(share["share"]["selected_assets"], [share_target["asset"].name])
        _assert_counts_delta(self, before_share, {"AI Tool Run Share": 1})

        for user in (self.viewer, self.billing, self.outsider, "Guest"):
            before_counts = _counts()
            before_snapshot = _snapshot()
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError) as exc:
                frappe.call("slow_ai.api.public_tools.disable_run_share", share_token=share["share"]["share_token"])
            _assert_safe_exception(self, exc.exception)
            frappe.set_user("Administrator")
            _assert_no_side_effects(self, before_counts, before_snapshot)

        before_disable = _counts()
        frappe.set_user(self.editor)
        disabled = frappe.call("slow_ai.api.public_tools.disable_run_share", share_token=share["share"]["share_token"])
        _assert_safe_payload(self, disabled)
        self.assertEqual(disabled["share"]["status"], "DISABLED")
        _assert_counts_delta(self, before_disable, {})

    def test_rerun_prepare_update_access_matrix_and_unsafe_rejections(self):
        project = self._new_project_with_members()
        frappe.set_user("Administrator")
        template = save_template(
            _unique("Write Matrix Rerun Template"),
            "PUBLISHED",
            text_tool_nodes("Original write matrix prompt", style="natural", steps=4),
            text_tool_edges(),
            input_schema=text_tool_input_schema(),
        )
        frappe.set_user(self.owner)
        source_draft = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Write Matrix Source Draft",
            values={"prompt": "Write matrix source", "style": "studio", "steps": 7},
        )
        source_run = frappe.call("slow_ai.api.runs.start_run", workflow=source_draft["name"])
        run_workflow(source_run["workflow_run"])

        for user in (self.viewer, self.billing, self.outsider, "Guest"):
            before_counts = _counts()
            before_snapshot = _snapshot()
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError) as exc:
                frappe.call("slow_ai.api.public_tools.prepare_rerun_from_run", workflow_run=source_run["workflow_run"])
            _assert_safe_exception(self, exc.exception)
            frappe.set_user("Administrator")
            _assert_no_side_effects(self, before_counts, before_snapshot)

        prepared_drafts = []
        for user in (self.owner, self.editor, "Administrator"):
            before = _counts()
            frappe.set_user(user)
            rerun = frappe.call("slow_ai.api.public_tools.prepare_rerun_from_run", workflow_run=source_run["workflow_run"])
            _assert_safe_payload(self, rerun)
            self.assertEqual(rerun["workflow"]["source_template"], template["name"])
            self.assertEqual(rerun["prefilled_values"]["prompt"], "Write matrix source")
            prepared_drafts.append(rerun["workflow"]["name"])
            _assert_counts_delta(self, before, {"AI Workflow": 1})

        draft_name = prepared_drafts[0]
        for user in (self.viewer, self.billing, self.outsider, "Guest"):
            before_counts = _counts()
            before_snapshot = _snapshot()
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError) as exc:
                frappe.call(
                    "slow_ai.api.public_tools.update_rerun_draft_values",
                    workflow=draft_name,
                    values={"prompt": "Denied update", "style": "natural", "steps": 3},
                )
            _assert_safe_exception(self, exc.exception)
            frappe.set_user("Administrator")
            _assert_no_side_effects(self, before_counts, before_snapshot)

        before_update_counts = _counts()
        frappe.set_user(self.owner)
        updated = frappe.call(
            "slow_ai.api.public_tools.update_rerun_draft_values",
            workflow=draft_name,
            values={"prompt": "Updated write matrix prompt", "style": "natural", "steps": 9},
        )
        _assert_safe_payload(self, updated)
        prompt_node = next(node for node in updated["nodes"] if node["id"] == "prompt_1")
        self.assertEqual(prompt_node["config"]["text"], "Updated write matrix prompt")
        self.assertEqual(prompt_node["config"]["text_style"], "natural")
        self.assertEqual(prompt_node["config"]["steps"], 9)
        _assert_counts_delta(self, before_update_counts, {})

        draft_before_rejections = frappe.db.get_value("AI Workflow", draft_name, "draft_nodes_json")
        for values in (
            {"prompt": "Valid", "provider_account": "forbidden"},
            {"prompt": "Valid", "raw_error_json": {"secret": "WRITE_ACTION_SECRET"}},
            {"prompt": "Valid", "unknown_field": "nope"},
        ):
            before_counts = _counts()
            before_snapshot = _snapshot()
            with self.assertRaises(frappe.ValidationError):
                frappe.call("slow_ai.api.public_tools.update_rerun_draft_values", workflow=draft_name, values=values)
            _assert_no_side_effects(self, before_counts, before_snapshot)
            self.assertEqual(frappe.db.get_value("AI Workflow", draft_name, "draft_nodes_json"), draft_before_rejections)

        owner_asset = frappe.call(
            "slow_ai.api.assets.upload",
            project=project.name,
            asset_type="IMAGE",
            url="https://example.invalid/write-matrix-owned.png",
            mime_type="image/png",
            metadata={"origin": "write-action-owned"},
        )
        other_project = create_project(self.outsider)
        frappe.set_user(self.outsider)
        inaccessible_asset = frappe.call(
            "slow_ai.api.assets.upload",
            project=other_project.name,
            asset_type="IMAGE",
            url="https://example.invalid/write-matrix-inaccessible.png",
            mime_type="image/png",
            metadata={"origin": "write-action-inaccessible"},
        )
        frappe.set_user("Administrator")
        upload_template = save_template(
            _unique("Write Matrix Upload Rerun Template"),
            "PUBLISHED",
            upload_tool_nodes(owner_asset["name"]),
            upload_tool_edges(),
        )
        frappe.set_user(self.owner)
        upload_draft = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=upload_template["name"],
            project=project.name,
            title="Write Matrix Upload Source Draft",
            values={"asset_1": {"asset": owner_asset["name"]}},
        )
        upload_run = frappe.call("slow_ai.api.runs.start_run", workflow=upload_draft["name"])
        run_workflow(upload_run["workflow_run"])
        upload_rerun = frappe.call("slow_ai.api.public_tools.prepare_rerun_from_run", workflow_run=upload_run["workflow_run"])
        upload_before = _counts()
        upload_snapshot = _snapshot()
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.public_tools.update_rerun_draft_values",
                workflow=upload_rerun["workflow"]["name"],
                values={"asset_1": {"asset": inaccessible_asset["name"]}},
            )
        _assert_no_side_effects(self, upload_before, upload_snapshot)

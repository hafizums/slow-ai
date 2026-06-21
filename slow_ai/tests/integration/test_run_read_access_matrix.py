import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date
from frappe.utils import now_datetime

from slow_ai.tests.integration.test_project_membership import ensure_user
from slow_ai.tests.integration.test_run_activity_timeline import add_provider_artifacts
from slow_ai.tests.integration.test_run_activity_timeline import create_manual_run
from slow_ai.tests.integration.test_run_activity_timeline import create_project
from slow_ai.tests.integration.test_run_activity_timeline import insert_doc


SIDE_EFFECT_DOCTYPES = (
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
)

MUTATION_SNAPSHOT_FIELDS = {
    "AI Workflow Version": ["name", "workflow", "snapshot_hash", "modified"],
    "AI Workflow Run": [
        "name",
        "status",
        "is_archived",
        "archived_by",
        "archived_at",
        "error_json",
        "modified",
    ],
    "AI Node Run": ["name", "workflow_run", "status", "provider_job", "cost_usd", "error_json", "modified"],
    "AI Provider Job": [
        "name",
        "node_run",
        "status",
        "poll_attempts",
        "last_polled_at",
        "retry_count",
        "raw_error_json",
        "modified",
    ],
    "AI Asset": [
        "name",
        "project",
        "source_workflow_run",
        "source_node_run",
        "source_provider_job",
        "metadata_json",
        "modified",
    ],
    "AI Credit Ledger": [
        "name",
        "project",
        "workflow_run",
        "node_run",
        "provider_job",
        "ledger_type",
        "amount_usd",
        "modified",
    ],
    "AI Tool Run Share": ["name", "workflow_run", "status", "selected_assets_json", "expires_at", "modified"],
}

UNSAFE_FRAGMENTS = (
    "run-read-access-provider-account",
    "RUN_READ_ACCESS_SECRET",
    "sk_run_read_access_should_not_leak",
    "https://provider.example.invalid",
    "request_json",
    "response_json",
    "raw_error_json",
    "api_key",
    "Authorization",
    "Bearer",
    "Traceback",
    "stack trace",
    "draft_nodes_json",
    "draft_edges_json",
    "nodes_json",
    "edges_json",
    "layout_json",
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


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


def _add_member(project: str, user: str, role: str):
    return insert_doc(
        {
            "doctype": "AI Project Member",
            "project": project,
            "user": user,
            "role": role,
            "status": "ACTIVE",
        }
    )


def _read_api_payloads(workflow_run: str, asset: str, project: str) -> list[dict]:
    return [
        frappe.call("slow_ai.api.runs.get_run_status", workflow_run=workflow_run),
        frappe.call("slow_ai.api.runs.get_history", workflow_run=workflow_run),
        frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=workflow_run),
        frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=workflow_run),
        frappe.call("slow_ai.api.public_tools.list_my_runs", project=project),
        frappe.call("slow_ai.api.public_tools.get_run_output_gallery", workflow_run=workflow_run),
        frappe.call("slow_ai.api.assets.view", asset=asset),
    ]


class TestRunReadAccessMatrix(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"run-read-owner-{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"run-read-editor-{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"run-read-viewer-{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"run-read-billing-{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"run-read-outsider-{uuid4().hex[:8]}@example.test")
        self.project = create_project(owner=self.owner)
        _add_member(self.project.name, self.editor, "EDITOR")
        _add_member(self.project.name, self.viewer, "VIEWER")
        _add_member(self.project.name, self.billing, "BILLING")
        _, _, self.run = create_manual_run(self.project, status="SUCCEEDED")
        self.node_run, self.provider_job, self.selected_asset = add_provider_artifacts(
            self.project,
            self.run,
            raw_secret="sk_run_read_access_should_not_leak",
        )
        self.unselected_asset = insert_doc(
            {
                "doctype": "AI Asset",
                "project": self.project.name,
                "asset_type": "IMAGE",
                "url": "https://safe-assets.example.invalid/unselected.png",
                "mime_type": "image/png",
                "source_workflow_run": self.run.name,
                "source_node_run": self.node_run.name,
                "source_provider_job": self.provider_job.name,
                "metadata_json": json.dumps(
                    {
                        "origin": "run-read-access",
                        "api_key": "RUN_READ_ACCESS_SECRET",
                        "provider_url": "https://provider.example.invalid/unselected",
                    }
                ),
            }
        )
        account = insert_doc(
            {
                "doctype": "AI Provider Account",
                "provider": "timeline_provider",
                "account_label": "run-read-access-provider-account",
                "api_key_secret": "RUN_READ_ACCESS_SECRET",
                "status": "ACTIVE",
            }
        )
        frappe.db.set_value(
            "AI Workflow Run",
            self.run.name,
            "error_json",
            json.dumps(
                {
                    "message": "Traceback Authorization Bearer sk_run_read_access_should_not_leak",
                    "raw_error_json": {"provider_url": "https://provider.example.invalid/run"},
                }
            ),
        )
        frappe.db.set_value(
            "AI Provider Job",
            self.provider_job.name,
            {
                "provider_account": account.name,
                "external_job_id": "https://provider.example.invalid/job",
                "request_json": json.dumps({"Authorization": "Bearer sk_run_read_access_should_not_leak"}),
                "response_json": json.dumps({"url": "https://provider.example.invalid/output"}),
                "raw_error_json": json.dumps({"api_key": "RUN_READ_ACCESS_SECRET"}),
            },
        )
        self.active_share = insert_doc(
            {
                "doctype": "AI Tool Run Share",
                "workflow_run": self.run.name,
                "project": self.project.name,
                "share_token": _unique("run-read-active-share"),
                "status": "ACTIVE",
                "selected_assets_json": json.dumps([self.selected_asset.name]),
            }
        )
        self.disabled_share = insert_doc(
            {
                "doctype": "AI Tool Run Share",
                "workflow_run": self.run.name,
                "project": self.project.name,
                "share_token": _unique("run-read-disabled-share"),
                "status": "DISABLED",
                "selected_assets_json": json.dumps([self.selected_asset.name]),
            }
        )
        self.expired_share = insert_doc(
            {
                "doctype": "AI Tool Run Share",
                "workflow_run": self.run.name,
                "project": self.project.name,
                "share_token": _unique("run-read-expired-share"),
                "status": "ACTIVE",
                "expires_at": add_to_date(now_datetime(), hours=-1),
                "selected_assets_json": json.dumps([self.selected_asset.name]),
            }
        )

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_project_view_roles_can_read_safe_run_gallery_and_asset_payloads(self):
        before_counts = _record_counts()
        before_snapshot = _mutation_snapshot()

        for user in (self.owner, self.editor, self.viewer, self.billing, "Administrator"):
            frappe.set_user(user)
            payloads = _read_api_payloads(self.run.name, self.selected_asset.name, self.project.name)
            for payload in payloads:
                _assert_safe_payload(self, payload)
            self.assertIn(self.run.name, {row["workflow_run"] for row in payloads[4]["runs"]})
            self.assertEqual(payloads[5]["run"]["workflow_run"], self.run.name)
            self.assertIn(self.selected_asset.name, {row["name"] for row in payloads[5]["assets"]})

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_counts, before_snapshot)

    def test_nonmember_and_guest_are_rejected_from_authenticated_read_apis_without_side_effects(self):
        before_counts = _record_counts()
        before_snapshot = _mutation_snapshot()

        for user in (self.outsider, "Guest"):
            frappe.set_user(user)
            for method, kwargs in (
                ("slow_ai.api.runs.get_run_status", {"workflow_run": self.run.name}),
                ("slow_ai.api.runs.get_history", {"workflow_run": self.run.name}),
                ("slow_ai.api.runs.get_run_timeline", {"workflow_run": self.run.name}),
                ("slow_ai.api.public_tools.get_my_run", {"workflow_run": self.run.name}),
                ("slow_ai.api.public_tools.list_my_runs", {"project": self.project.name}),
                ("slow_ai.api.public_tools.get_run_output_gallery", {"workflow_run": self.run.name}),
                ("slow_ai.api.assets.view", {"asset": self.selected_asset.name}),
            ):
                with self.assertRaises(frappe.PermissionError, msg=f"{user} unexpectedly read {method}"):
                    frappe.call(method, **kwargs)

        frappe.set_user(self.outsider)
        runs = frappe.call("slow_ai.api.public_tools.list_my_runs")
        self.assertNotIn(self.run.name, {row["workflow_run"] for row in runs["runs"]})

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_counts, before_snapshot)

    def test_guest_shared_run_token_reads_are_selected_only_safe_and_side_effect_free(self):
        before_counts = _record_counts()
        before_snapshot = _mutation_snapshot()

        frappe.set_user("Guest")
        payload = frappe.call("slow_ai.api.public_tools.get_shared_run", share_token=self.active_share.share_token)
        _assert_safe_payload(self, payload)

        self.assertEqual({row["name"] for row in payload["assets"]}, {self.selected_asset.name})
        self.assertEqual({row["name"] for row in payload["output_gallery"]["assets"]}, {self.selected_asset.name})
        grouped_names = {
            asset["name"] for group in payload["output_gallery"]["groups"] for asset in group.get("assets", [])
        }
        self.assertEqual(grouped_names, {self.selected_asset.name})
        self.assertNotIn(self.unselected_asset.name, json.dumps(payload, default=str))
        self.assertNotIn("project", payload["run"])
        self.assertNotIn("project", payload["output_gallery"]["run"])
        self.assertNotIn("workflow", payload["output_gallery"]["run"])

        for token in (self.disabled_share.share_token, self.expired_share.share_token, _unique("missing-share")):
            with self.assertRaises(frappe.PermissionError):
                frappe.call("slow_ai.api.public_tools.get_shared_run", share_token=token)

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_counts, before_snapshot)

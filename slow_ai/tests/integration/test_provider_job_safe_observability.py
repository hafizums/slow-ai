import json
from pathlib import Path
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.tests.integration.test_project_membership import ensure_user
from slow_ai.tests.integration.test_public_tool_page import add_member
from slow_ai.tests.integration.test_run_activity_timeline import add_provider_artifacts
from slow_ai.tests.integration.test_run_activity_timeline import create_manual_run
from slow_ai.tests.integration.test_run_activity_timeline import create_project
from slow_ai.tests.integration.test_run_activity_timeline import insert_doc


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
    "AI Workflow": ["name", "project", "title", "status", "modified"],
    "AI Workflow Version": ["name", "workflow", "snapshot_hash", "modified"],
    "AI Workflow Run": ["name", "workflow", "project", "status", "error_json", "modified"],
    "AI Node Run": ["name", "workflow_run", "status", "provider_job", "error_json", "modified"],
    "AI Provider Job": [
        "name",
        "node_run",
        "provider",
        "provider_account",
        "status",
        "external_job_id",
        "poll_attempts",
        "last_polled_at",
        "request_json",
        "response_json",
        "raw_error_json",
        "modified",
    ],
    "AI Asset": ["name", "project", "source_workflow_run", "source_provider_job", "metadata_json", "modified"],
    "AI Credit Ledger": ["name", "project", "workflow_run", "provider_job", "ledger_type", "amount_usd", "modified"],
    "AI Tool Run Share": ["name", "workflow_run", "status", "selected_assets_json", "modified"],
}

SECRET = "PROVIDER_OBSERVABILITY_SECRET"
RAW_PROVIDER_URL = "https://provider.example.invalid/provider-observability"
UNSAFE_FRAGMENTS = (
    SECRET,
    RAW_PROVIDER_URL,
    "provider-observability-account-label",
    "api_key",
    "api_key_secret",
    "provider_account",
    "request_json",
    "response_json",
    "raw_error_json",
    "Authorization",
    "Bearer",
    "Traceback",
    "stack trace",
    "ProviderAdapter",
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


def _read_observability_payloads(workflow_run: str, project: str, asset: str) -> list[dict]:
    return [
        frappe.call("slow_ai.api.runs.get_run_status", workflow_run=workflow_run),
        frappe.call("slow_ai.api.runs.get_history", workflow_run=workflow_run),
        frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=workflow_run),
        frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=workflow_run),
        frappe.call("slow_ai.api.public_tools.list_my_runs", project=project),
        frappe.call("slow_ai.api.public_tools.get_run_output_gallery", workflow_run=workflow_run),
        frappe.call("slow_ai.api.assets.view", asset=asset),
    ]


class TestProviderJobSafeObservability(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"provider-observe-owner-{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"provider-observe-editor-{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"provider-observe-viewer-{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"provider-observe-billing-{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"provider-observe-outsider-{uuid4().hex[:8]}@example.test")
        self.project = create_project(owner=self.owner)
        add_member(self.project.name, self.editor, "EDITOR")
        add_member(self.project.name, self.viewer, "VIEWER")
        add_member(self.project.name, self.billing, "BILLING")
        _, _, self.run = create_manual_run(self.project, status="SUCCEEDED")
        self.node_run, self.provider_job, self.asset = add_provider_artifacts(
            self.project,
            self.run,
            provider_status="SUCCEEDED",
            raw_secret=SECRET,
        )
        self.account = insert_doc(
            {
                "doctype": "AI Provider Account",
                "provider": self.provider_job.provider,
                "account_label": "provider-observability-account-label",
                "api_key_secret": SECRET,
                "project": self.project.name,
                "status": "ACTIVE",
            }
        )
        frappe.db.set_value(
            "AI Provider Job",
            self.provider_job.name,
            {
                "provider_account": self.account.name,
                "external_job_id": f"{RAW_PROVIDER_URL}/job",
                "request_json": json.dumps({"Authorization": f"Bearer {SECRET}", "url": f"{RAW_PROVIDER_URL}/request"}),
                "response_json": json.dumps({"api_key": SECRET, "url": f"{RAW_PROVIDER_URL}/response"}),
                "raw_error_json": json.dumps(
                    {
                        "message": f"Provider warning api_key={SECRET} at {RAW_PROVIDER_URL}/error",
                        "code": "provider_observability_warning",
                        "Traceback": "stack trace should stay server-side",
                    }
                ),
            },
        )
        self.provider_job.reload()
        self.share = insert_doc(
            {
                "doctype": "AI Tool Run Share",
                "workflow_run": self.run.name,
                "project": self.project.name,
                "share_token": _unique("provider-observe-share"),
                "status": "ACTIVE",
                "selected_assets_json": json.dumps([self.asset.name]),
            }
        )

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_project_view_roles_see_only_safe_provider_job_observability(self):
        before_counts = _record_counts()
        before_snapshot = _mutation_snapshot()

        for user in (self.owner, self.editor, self.viewer, self.billing, "Administrator"):
            frappe.set_user(user)
            payloads = _read_observability_payloads(self.run.name, self.project.name, self.asset.name)
            for payload in payloads:
                _assert_safe_payload(self, payload)

            history = payloads[1]
            provider_summary = next(row for row in history["provider_jobs"] if row["name"] == self.provider_job.name)
            self.assertEqual(provider_summary["provider"], self.provider_job.provider)
            self.assertEqual(provider_summary["model"], self.provider_job.model)
            self.assertEqual(provider_summary["status"], self.provider_job.status)
            self.assertEqual(provider_summary["poll_attempts"], self.provider_job.poll_attempts)
            self.assertIn("last_polled_at", provider_summary)
            self.assertIn("estimated_cost_usd", provider_summary)
            self.assertIn("debit_cost_source", provider_summary)
            self.assertNotIn("provider_account", provider_summary)
            self.assertNotIn("external_job_id", provider_summary)
            self.assertNotIn("request_json", provider_summary)
            self.assertNotIn("response_json", provider_summary)
            self.assertNotIn("raw_error_json", provider_summary)

            timeline = payloads[2]
            provider_events = [
                event
                for event in timeline["events"]
                if event.get("related_doctype") == "AI Provider Job"
                and event.get("related_name") == self.provider_job.name
            ]
            self.assertTrue(provider_events)
            for event in provider_events:
                self.assertIn(event["event_type"], {"PROVIDER_JOB_CREATED", "PROVIDER_JOB_SUBMITTED", "PROVIDER_JOB_POLLED", "PROVIDER_JOB_SUCCEEDED"})
                self.assertEqual(event["status"], self.provider_job.status)

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_counts, before_snapshot)

    def test_nonmember_and_guest_cannot_read_internal_provider_job_observability(self):
        before_counts = _record_counts()
        before_snapshot = _mutation_snapshot()

        for user in (self.outsider, "Guest"):
            frappe.set_user(user)
            for method, kwargs in (
                ("slow_ai.api.runs.get_run_status", {"workflow_run": self.run.name}),
                ("slow_ai.api.runs.get_history", {"workflow_run": self.run.name}),
                ("slow_ai.api.runs.get_run_timeline", {"workflow_run": self.run.name}),
                ("slow_ai.api.public_tools.get_my_run", {"workflow_run": self.run.name}),
                ("slow_ai.api.public_tools.get_run_output_gallery", {"workflow_run": self.run.name}),
                ("slow_ai.api.assets.view", {"asset": self.asset.name}),
            ):
                with self.assertRaises(frappe.PermissionError, msg=f"{user} unexpectedly read {method}"):
                    frappe.call(method, **kwargs)

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_counts, before_snapshot)

    def test_guest_shared_run_exposes_selected_assets_but_no_provider_job_observability(self):
        before_counts = _record_counts()
        before_snapshot = _mutation_snapshot()

        frappe.set_user("Guest")
        payload = frappe.call("slow_ai.api.public_tools.get_shared_run", share_token=self.share.share_token)
        encoded = json.dumps(payload, default=str)

        self.assertEqual({asset["name"] for asset in payload["assets"]}, {self.asset.name})
        self.assertNotIn("provider_jobs", payload)
        self.assertNotIn("provider_summary", payload)
        self.assertNotIn(self.provider_job.name, encoded)
        self.assertNotIn("source_provider_job", encoded)
        _assert_safe_payload(self, payload)

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_counts, before_snapshot)

    def test_provider_job_observability_static_frontend_boundary(self):
        app_path = Path(frappe.get_app_path("slow_ai"))
        sources = [
            app_path / "slow_ai/page/slow_ai_canvas/slow_ai_canvas.js",
            app_path / "slow_ai/page/slow_ai_tools/slow_ai_tools.js",
            app_path / "www/slow-ai/shared.html",
        ]
        forbidden = (
            "external_job_id",
            "request_json",
            "response_json",
            "raw_error_json",
            "api_key_secret",
            "Authorization: Bearer",
            "ProviderAdapter",
            "ProviderRegistry",
            "api.wavespeed.ai",
            "api.replicate.com",
            "frappe.db",
            "frappe.enqueue",
        )
        for source_path in sources:
            source = source_path.read_text()
            for fragment in forbidden:
                self.assertNotIn(fragment, source, f"{fragment} in {source_path}")

import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.tests.integration.test_project_membership import ensure_user
from slow_ai.tests.integration.test_run_recovery_admin_tools import _make_provider_waiting_run


READ_SIDE_EFFECT_DOCTYPES = (
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
)

MUTATION_FIELDS = {
    "AI Workflow Version": ["name", "modified"],
    "AI Workflow Run": ["name", "status", "error_json", "modified"],
    "AI Node Run": ["name", "status", "provider_job", "error_json", "modified"],
    "AI Provider Job": ["name", "status", "poll_attempts", "raw_error_json", "modified"],
    "AI Asset": ["name", "source_workflow_run", "source_provider_job", "modified"],
    "AI Credit Ledger": ["name", "ledger_type", "amount_usd", "modified"],
    "AI Tool Run Share": ["name", "status", "modified"],
}

UNSAFE_FRAGMENTS = (
    "observability-secret",
    "raw-recovery-secret",
    "request_json",
    "response_json",
    "raw_error_json",
    '"provider_account"',
    "external_job_id",
    "api_key",
    "Authorization",
    "Bearer",
    "Traceback",
    "https://provider.example.invalid",
)


def snapshot() -> dict[str, list[dict]]:
    rows = {}
    for doctype, fields in MUTATION_FIELDS.items():
        rows[doctype] = [dict(row) for row in frappe.get_all(doctype, fields=fields, order_by="name asc")]
    return json.loads(json.dumps(rows, default=str))


def counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in READ_SIDE_EFFECT_DOCTYPES}


def assert_no_side_effects(testcase: FrappeTestCase, before_counts: dict[str, int], before_snapshot: dict[str, list[dict]]):
    testcase.assertEqual(counts(), before_counts)
    testcase.assertEqual(snapshot(), before_snapshot)


def assert_safe_payload(testcase: FrappeTestCase, payload):
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


class TestAdminSafeObservability(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.non_manager = ensure_user(f"observability.viewer.{uuid4().hex[:8]}@example.test")

    def tearDown(self):
        frappe.set_user("Administrator")

    def _create_observable_run(self):
        project, workflow, start, adapter, provider_job = _make_provider_waiting_run()
        account_name = frappe.db.get_value("AI Provider Job", provider_job.name, "provider_account")
        if account_name:
            frappe.db.set_value("AI Provider Account", account_name, "account_label", "observability-secret-account")
        frappe.db.set_value(
            "AI Provider Job",
            provider_job.name,
            {
                "request_json": json.dumps({"Authorization": "Bearer observability-secret"}),
                "response_json": json.dumps({"url": "https://provider.example.invalid/unsafe-output"}),
                "raw_error_json": json.dumps({"api_key": "observability-secret", "trace": "Traceback unsafe"}),
                "external_job_id": "observability-secret-external-job",
            },
        )
        return project, workflow, start, adapter, provider_job

    def test_system_manager_observability_apis_are_safe_and_read_only(self):
        _, _, start, adapter, provider_job = self._create_observable_run()
        before_counts = counts()
        before_snapshot = snapshot()

        overview = frappe.call("slow_ai.api.admin.get_system_overview")
        runs = frappe.call("slow_ai.api.admin.list_run_health", status="ALL", limit=25)
        provider_jobs = frappe.call("slow_ai.api.admin.list_provider_job_health", status="ALL", limit=25)
        billing = frappe.call("slow_ai.api.admin.list_billing_health", limit=25)

        assert_no_side_effects(self, before_counts, before_snapshot)
        for payload in (overview, runs, provider_jobs, billing):
            assert_safe_payload(self, payload)

        self.assertIn("workflow_runs", overview)
        self.assertIn("provider_jobs", overview)
        self.assertIn("billing", overview)
        self.assertTrue(any(row["workflow_run"] == start.workflow_run for row in runs["runs"]))
        job_row = next(row for row in provider_jobs["provider_jobs"] if row["provider_job"] == provider_job.name)
        self.assertEqual(job_row["status"], frappe.db.get_value("AI Provider Job", provider_job.name, "status"))
        self.assertNotIn("provider_account", job_row)
        self.assertNotIn("external_job_id", job_row)
        self.assertTrue(billing["projects"])
        self.assertEqual(adapter.polled, [])

    def test_non_system_manager_observability_is_denied_without_side_effects(self):
        self._create_observable_run()
        for user in (self.non_manager, "Guest"):
            frappe.set_user(user)
            before_counts = counts()
            before_snapshot = snapshot()
            for method in (
                "slow_ai.api.admin.get_system_overview",
                "slow_ai.api.admin.list_run_health",
                "slow_ai.api.admin.list_provider_job_health",
                "slow_ai.api.admin.list_billing_health",
            ):
                with self.assertRaises(frappe.PermissionError):
                    frappe.call(method)
            assert_no_side_effects(self, before_counts, before_snapshot)

    def test_client_sources_do_not_call_admin_observability_apis(self):
        bench_path = frappe.utils.get_bench_path()
        for relative_path in (
            "slow_ai/page/slow_ai_canvas/slow_ai_canvas.js",
            "slow_ai/page/slow_ai_tools/slow_ai_tools.js",
            "www/slow-ai/shared.html",
        ):
            with open(f"{bench_path}/apps/slow_ai/slow_ai/{relative_path}") as handle:
                source = handle.read()
            self.assertNotIn("slow_ai.api.admin.", source)
            self.assertNotIn("get_system_overview", source)
            self.assertNotIn("list_provider_job_health", source)

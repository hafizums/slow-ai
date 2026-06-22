import json
import re
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.tests.integration.test_project_membership import ensure_user
from slow_ai.tests.integration.test_run_recovery_admin_tools import _make_provider_waiting_run


ALLOWED_ADMIN_METHODS = {
    "slow_ai.api.admin.get_system_overview",
    "slow_ai.api.admin.list_run_health",
    "slow_ai.api.admin.list_provider_job_health",
    "slow_ai.api.admin.list_billing_health",
}

SIDE_EFFECT_DOCTYPES = (
    "AI Workflow",
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
    "AI Provider Account",
    "AI Model",
    "AI Workflow Template",
    "AI Workflow Template Version",
)

MUTATION_FIELDS = {
    "AI Workflow": ["name", "status", "modified"],
    "AI Workflow Version": ["name", "modified"],
    "AI Workflow Run": ["name", "status", "error_json", "modified"],
    "AI Node Run": ["name", "status", "provider_job", "error_json", "modified"],
    "AI Provider Job": ["name", "status", "poll_attempts", "raw_error_json", "modified"],
    "AI Asset": ["name", "source_workflow_run", "source_provider_job", "modified"],
    "AI Credit Ledger": ["name", "ledger_type", "amount_usd", "modified"],
    "AI Tool Run Share": ["name", "status", "modified"],
    "AI Provider Account": ["name", "status", "is_default", "modified"],
    "AI Model": ["name", "status", "pricing_json", "modified"],
    "AI Workflow Template": ["name", "status", "published_version", "modified"],
    "AI Workflow Template Version": ["name", "status", "modified"],
}

FORBIDDEN_ADMIN_SOURCE_FRAGMENTS = (
    "ProviderAdapter",
    "ProviderRegistry",
    "api.wavespeed.ai",
    "api.replicate.com",
    "api_key_secret",
    "provider_account",
    "external_job_id",
    "request_json",
    "response_json",
    "raw_error_json",
    "Authorization",
    "Bearer",
    "frappe.db",
    "frappe.enqueue",
    "inspect_run_recovery",
    "expire_stuck_run",
    "resume_run",
    "WorkflowExecutor",
    "run_workflow",
    "submit_job",
    "poll_job",
    "checkpoint",
    "KSampler",
    "CUDA",
    "local model",
)


def counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def snapshot() -> dict[str, list[dict]]:
    result = {}
    for doctype, fields in MUTATION_FIELDS.items():
        result[doctype] = [dict(row) for row in frappe.get_all(doctype, fields=fields, order_by="name asc")]
    return json.loads(json.dumps(result, default=str))


def assert_no_side_effects(testcase: FrappeTestCase, before_counts: dict[str, int], before_snapshot: dict[str, list[dict]]):
    testcase.assertEqual(counts(), before_counts)
    testcase.assertEqual(snapshot(), before_snapshot)


class TestAdminObservabilityPage(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.non_manager = ensure_user(f"admin.page.viewer.{uuid4().hex[:8]}@example.test")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_admin_page_uses_only_safe_admin_apis_and_has_safe_states(self):
        frappe.reload_doc("slow_ai", "page", "slow_ai_admin")
        page = frappe.get_doc("Page", "slow-ai-admin")
        page.load_assets()

        self.assertEqual(page.module, "Slow Ai")
        self.assertIn('frappe.pages["slow-ai-admin"]', page.script)
        self.assertIn('data-page="slow-ai-admin"', page.script)
        self.assertIn("System health unavailable", page.script)
        self.assertIn("Run health unavailable", page.script)
        self.assertIn("Provider job health unavailable", page.script)
        self.assertIn("Billing health unavailable", page.script)
        self.assertIn("No workflow runs found", page.script)
        self.assertIn("No provider jobs found", page.script)
        self.assertIn("No project billing rows found", page.script)
        self.assertIn("Loading system health", page.script)
        self.assertIn("renderSectionError", page.script)
        self.assertIn("renderEmpty", page.script)
        self.assertIn("renderLoading", page.script)

        methods = set(re.findall(r"frappe\s*\.\s*call\(\s*[\"']([^\"']+)[\"']", page.script))
        self.assertEqual(methods, ALLOWED_ADMIN_METHODS)
        for fragment in FORBIDDEN_ADMIN_SOURCE_FRAGMENTS:
            self.assertNotIn(fragment, page.script, fragment)

    def test_admin_page_backing_reads_are_side_effect_free_for_allowed_and_denied_users(self):
        _make_provider_waiting_run()
        frappe.set_user("Administrator")
        before_counts = counts()
        before_snapshot = snapshot()
        frappe.call("slow_ai.api.admin.get_system_overview")
        frappe.call("slow_ai.api.admin.list_run_health", status="ALL", limit=10)
        frappe.call("slow_ai.api.admin.list_provider_job_health", status="ALL", limit=10)
        frappe.call("slow_ai.api.admin.list_billing_health", limit=10)
        assert_no_side_effects(self, before_counts, before_snapshot)

        frappe.set_user(self.non_manager)
        before_counts = counts()
        before_snapshot = snapshot()
        for method in ALLOWED_ADMIN_METHODS:
            with self.assertRaises(frappe.PermissionError):
                frappe.call(method)
        assert_no_side_effects(self, before_counts, before_snapshot)

    def test_canvas_public_and_shared_pages_do_not_reference_admin_observability(self):
        bench_path = frappe.utils.get_bench_path()
        for relative_path in (
            "slow_ai/slow_ai/page/slow_ai_canvas/slow_ai_canvas.js",
            "slow_ai/slow_ai/page/slow_ai_tools/slow_ai_tools.js",
            "slow_ai/www/slow-ai/shared.html",
        ):
            with open(f"{bench_path}/apps/slow_ai/{relative_path}") as handle:
                source = handle.read()
            self.assertNotIn("slow_ai.api.admin.", source)
            self.assertNotIn("slow-ai-admin", source)

    def test_nearby_operational_panels_have_generic_empty_or_error_states(self):
        bench_path = frappe.utils.get_bench_path()
        with open(f"{bench_path}/apps/slow_ai/slow_ai/slow_ai/page/slow_ai_canvas/slow_ai_canvas.js") as handle:
            canvas_source = handle.read()
        with open(f"{bench_path}/apps/slow_ai/slow_ai/slow_ai/page/slow_ai_tools/slow_ai_tools.js") as handle:
            tools_source = handle.read()

        for fragment in (
            "Loading provider accounts",
            "No provider accounts",
            "Loading model catalog",
            "No assets yet",
            "Timeline unavailable",
        ):
            self.assertIn(fragment, canvas_source)

        for fragment in (
            "Balance unavailable",
            "Project member management unavailable",
            "No project members",
            "Timeline unavailable",
            "No timeline events",
            "No output assets are available to share",
        ):
            self.assertIn(fragment, tools_source)

import json
from decimal import Decimal
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.billing import get_balance
from slow_ai.application.run_recovery import expire_stuck_run
from slow_ai.application.run_recovery import inspect_run_recovery
from slow_ai.application.run_recovery import resume_run
from slow_ai.application.run_service import RunService
from slow_ai.engine.executor import WorkflowExecutor
from slow_ai.tests.integration.test_billing_credit_reservation import create_project
from slow_ai.tests.integration.test_billing_credit_reservation import ledger_counts
from slow_ai.tests.integration.test_billing_credit_reservation import provider_job_for_run
from slow_ai.tests.integration.test_billing_credit_reservation import registry
from slow_ai.tests.integration.test_billing_credit_reservation import setup_provider_run
from slow_ai.tests.integration.test_project_membership import ensure_user


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
    "AI Provider Job": ["name", "node_run", "provider", "status", "raw_error_json", "modified"],
    "AI Asset": ["name", "project", "source_workflow_run", "source_provider_job", "modified"],
    "AI Credit Ledger": ["name", "project", "workflow_run", "provider_job", "ledger_type", "amount_usd", "modified"],
    "AI Tool Run Share": ["name", "workflow_run", "status", "modified"],
}

UNSAFE_FRAGMENTS = (
    "reservation-provider-secret",
    "raw-recovery-secret",
    "request_json",
    "response_json",
    "raw_error_json",
    "provider_account",
    "external_job_id",
    "api_key",
    "Authorization",
    "Bearer",
    "Traceback",
    "https://provider.example.invalid",
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def _snapshot() -> dict[str, list[dict]]:
    rows = {}
    for doctype, fields in MUTATION_SNAPSHOT_FIELDS.items():
        rows[doctype] = [dict(row) for row in frappe.get_all(doctype, fields=fields, order_by="name asc")]
    return json.loads(json.dumps(rows, default=str))


def _assert_no_side_effects(testcase: FrappeTestCase, before_counts: dict[str, int], before_snapshot: dict[str, list[dict]]):
    testcase.assertEqual(_counts(), before_counts)
    testcase.assertEqual(_snapshot(), before_snapshot)


def _assert_safe_payload(testcase: FrappeTestCase, payload):
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


def _add_member(project: str, user: str, role: str):
    return frappe.get_doc(
        {
            "doctype": "AI Project Member",
            "project": project,
            "user": user,
            "role": role,
            "status": "ACTIVE",
        }
    ).insert(ignore_permissions=True)


def _create_text_workflow(project):
    return frappe.get_doc(
        {
            "doctype": "AI Workflow",
            "title": _unique("Recovery Text Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Recovery prompt"}},
                    {"id": "output_1", "type": "export_output", "config": {}},
                ]
            ),
            "draft_edges_json": json.dumps(
                [
                    {
                        "id": "edge_1",
                        "source": "prompt_1",
                        "source_port": "text",
                        "target": "output_1",
                        "target_port": "text",
                    }
                ]
            ),
            "layout_json": "{}",
        }
    ).insert(ignore_permissions=True)


def _make_provider_waiting_run():
    project, workflow, adapter = setup_provider_run()
    start = RunService(node_registry=registry(adapter)).start_run(workflow.name)
    WorkflowExecutor(node_registry=registry(adapter)).run(start.workflow_run)
    provider_job = provider_job_for_run(start.workflow_run)
    frappe.db.set_value(
        "AI Provider Job",
        provider_job.name,
        {
            "request_json": json.dumps({"Authorization": "Bearer raw-recovery-secret"}),
            "response_json": json.dumps({"url": "https://provider.example.invalid/recovery"}),
            "raw_error_json": json.dumps({"api_key": "raw-recovery-secret"}),
        },
    )
    return project, workflow, start, adapter, provider_job


class TestRunRecoveryAdminTools(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"run-recovery-owner-{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"run-recovery-editor-{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"run-recovery-viewer-{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"run-recovery-billing-{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"run-recovery-outsider-{uuid4().hex[:8]}@example.test")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_system_manager_can_inspect_resume_and_expire_stale_run_safely(self):
        project, _, start, adapter, provider_job = _make_provider_waiting_run()

        inspected = inspect_run_recovery(start.workflow_run, max_age_minutes=0)
        resumed = resume_run(start.workflow_run)
        expired = expire_stuck_run(start.workflow_run, max_age_minutes=0, reason="Recovery test expiry")
        repeated = expire_stuck_run(start.workflow_run, max_age_minutes=0, reason="Recovery test expiry")

        for payload in (inspected, resumed, expired, repeated):
            _assert_safe_payload(self, payload)
        self.assertEqual(resumed["queue_job_id"], f"slow_ai:workflow_run:{start.workflow_run}")
        self.assertEqual(expired["run"]["status"], "EXPIRED")
        self.assertEqual(repeated["run"]["status"], "EXPIRED")
        self.assertEqual(frappe.db.get_value("AI Workflow Run", start.workflow_run, "status"), "EXPIRED")
        self.assertEqual(frappe.db.get_value("AI Provider Job", provider_job.name, "status"), "CANCELLED")
        self.assertEqual(ledger_counts(start.workflow_run).get("RESERVE"), 1)
        self.assertEqual(ledger_counts(start.workflow_run).get("RELEASE"), 1)
        self.assertIsNone(ledger_counts(start.workflow_run).get("DEBIT"))
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job.name}), 0)
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("1.00"))
        self.assertEqual(adapter.polled, [])

    def test_non_system_manager_roles_are_denied_without_side_effects(self):
        project, _, start, _, _ = _make_provider_waiting_run()
        frappe.db.set_value("AI Project", project.name, "owner", self.owner)
        _add_member(project.name, self.editor, "EDITOR")
        _add_member(project.name, self.viewer, "VIEWER")
        _add_member(project.name, self.billing, "BILLING")
        users = [self.owner, self.editor, self.viewer, self.billing, self.outsider, "Guest"]

        for user in users:
            frappe.set_user(user)
            before_counts = _counts()
            before_snapshot = _snapshot()
            for method, kwargs in (
                ("slow_ai.api.runs.inspect_run_recovery", {"workflow_run": start.workflow_run}),
                ("slow_ai.api.runs.resume_run", {"workflow_run": start.workflow_run}),
                ("slow_ai.api.runs.expire_stuck_run", {"workflow_run": start.workflow_run, "max_age_minutes": 0}),
            ):
                with self.assertRaises(frappe.PermissionError):
                    frappe.call(method, **kwargs)
            _assert_no_side_effects(self, before_counts, before_snapshot)

    def test_terminal_runs_are_not_resumed_and_valid_active_runs_are_not_expired(self):
        project = create_project()
        workflow = _create_text_workflow(project)
        start = RunService().start_run(workflow.name)

        with self.assertRaises(frappe.ValidationError):
            expire_stuck_run(start.workflow_run, max_age_minutes=60)
        before_counts = _counts()
        before_snapshot = _snapshot()
        resume_payload = resume_run(start.workflow_run)
        self.assertEqual(resume_payload["queue_job_id"], f"slow_ai:workflow_run:{start.workflow_run}")
        _assert_no_side_effects(self, before_counts, before_snapshot)

        WorkflowExecutor().run(start.workflow_run)
        with self.assertRaises(frappe.ValidationError):
            resume_run(start.workflow_run)
        with self.assertRaises(frappe.ValidationError):
            expire_stuck_run(start.workflow_run, max_age_minutes=0)
        self.assertEqual(frappe.db.get_value("AI Workflow Run", start.workflow_run, "status"), "SUCCEEDED")

    def test_recovery_expiry_handles_stale_reservations_without_provider_calls(self):
        project, _, start, adapter, provider_job = _make_provider_waiting_run()
        before_provider_jobs = frappe.db.count("AI Provider Job")
        before_assets = frappe.db.count("AI Asset")

        expired = frappe.call(
            "slow_ai.api.runs.expire_stuck_run",
            workflow_run=start.workflow_run,
            max_age_minutes=0,
            reason="Release stale reservation",
        )

        self.assertEqual(expired["run"]["status"], "EXPIRED")
        self.assertEqual(adapter.polled, [])
        self.assertEqual(frappe.db.count("AI Provider Job"), before_provider_jobs)
        self.assertEqual(frappe.db.count("AI Asset"), before_assets)
        self.assertEqual(frappe.db.get_value("AI Provider Job", provider_job.name, "status"), "CANCELLED")
        self.assertEqual(ledger_counts(start.workflow_run).get("RESERVE"), 1)
        self.assertEqual(ledger_counts(start.workflow_run).get("RELEASE"), 1)
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("1.00"))

    def test_static_client_sources_do_not_call_recovery_admin_apis(self):
        for relative_path in (
            "slow_ai/page/slow_ai_canvas/slow_ai_canvas.js",
            "slow_ai/page/slow_ai_tools/slow_ai_tools.js",
            "www/slow-ai/shared.html",
        ):
            source = (frappe.utils.get_bench_path() + f"/apps/slow_ai/slow_ai/{relative_path}")
            with open(source) as handle:
                text = handle.read()
            self.assertNotIn("slow_ai.api.runs.inspect_run_recovery", text)
            self.assertNotIn("slow_ai.api.runs.expire_stuck_run", text)
            self.assertNotIn("slow_ai.api.runs.resume_run", text)

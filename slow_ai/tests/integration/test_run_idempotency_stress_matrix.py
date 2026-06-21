import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.run_recovery import expire_stuck_run, inspect_run_recovery, resume_run
from slow_ai.application.run_service import RunService
from slow_ai.engine.executor import WorkflowExecutor
from slow_ai.providers.registry import ProviderRegistry
from slow_ai.tests.integration.test_billing_credit_reservation import ledger_counts
from slow_ai.tests.integration.test_public_tool_page import add_member
from slow_ai.tests.integration.test_public_tool_page import create_shareable_asset_run
from slow_ai.tests.integration.test_public_tool_page import create_text_tool_run
from slow_ai.tests.integration.test_public_tool_page import ensure_user
from slow_ai.tests.integration.test_run_idempotency_recovery import IdempotencyProviderAdapter
from slow_ai.tests.integration.test_run_idempotency_recovery import create_project
from slow_ai.tests.integration.test_run_idempotency_recovery import create_provider_account
from slow_ai.tests.integration.test_run_idempotency_recovery import create_provider_model
from slow_ai.tests.integration.test_run_idempotency_recovery import create_provider_workflow
from slow_ai.tests.integration.test_run_idempotency_recovery import create_text_workflow
from slow_ai.tests.integration.test_run_idempotency_recovery import registry
from slow_ai.tests.integration.test_run_recovery_admin_tools import _make_provider_waiting_run
from slow_ai.workers.poll_provider_job import poll_pending_provider_jobs, poll_provider_job
from slow_ai.workers.resume_workflow import resume_workflow
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

UNSAFE_FRAGMENTS = (
    "stress-provider-secret",
    "idempotency-secret",
    "provider_account",
    "external_job_id",
    "request_json",
    "response_json",
    "raw_error_json",
    "api_key",
    "Authorization",
    "Bearer",
    "Traceback",
    "https://provider.example.invalid",
)


def _counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def _assert_counts_delta(testcase: FrappeTestCase, before: dict[str, int], delta: dict[str, int]) -> None:
    after = _counts()
    for doctype, count in before.items():
        testcase.assertEqual(after[doctype], count + delta.get(doctype, 0), doctype)


def _safe_payload(testcase: FrappeTestCase, payload) -> None:
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


def _provider_job_for_run(workflow_run: str) -> str:
    node_runs = frappe.get_all("AI Node Run", filters={"workflow_run": workflow_run}, pluck="name")
    return frappe.db.get_value("AI Provider Job", {"node_run": ["in", node_runs]}, "name")


class TestRunIdempotencyStressMatrix(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.user = ensure_user(f"stress-owner-{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"stress-viewer-{uuid4().hex[:8]}@example.test")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_duplicate_start_worker_and_resume_keep_one_active_text_run(self):
        workflow = create_text_workflow(create_project())
        before = _counts()

        first = RunService().start_run(workflow.name)
        second = RunService().start_run(workflow.name)
        run_workflow(first.workflow_run)
        resume_workflow(first.workflow_run)
        run_workflow(first.workflow_run)

        self.assertEqual(second.workflow_version, first.workflow_version)
        self.assertEqual(second.workflow_run, first.workflow_run)
        self.assertEqual(second.node_runs, first.node_runs)
        self.assertEqual(frappe.db.get_value("AI Workflow Run", first.workflow_run, "status"), "SUCCEEDED")
        self.assertEqual(frappe.db.count("AI Workflow Version", {"workflow": workflow.name}), 1)
        self.assertEqual(frappe.db.count("AI Workflow Run", {"workflow": workflow.name}), 1)
        self.assertEqual(frappe.db.count("AI Node Run", {"workflow_run": first.workflow_run}), 2)
        _assert_counts_delta(
            self,
            before,
            {
                "AI Workflow Version": 1,
                "AI Workflow Run": 1,
                "AI Node Run": 2,
            },
        )

        terminal = RunService().start_run(workflow.name)
        self.assertNotEqual(terminal.workflow_run, first.workflow_run)
        self.assertEqual(frappe.db.count("AI Workflow Run", {"workflow": workflow.name}), 2)

    def test_worker_poller_and_pending_batch_do_not_duplicate_provider_side_effects(self):
        adapter = IdempotencyProviderAdapter()
        project = create_project()
        model = create_provider_model(adapter.provider_name)
        create_provider_account(adapter.provider_name)
        frappe.get_attr("slow_ai.application.billing.create_top_up")(
            project.name,
            "1.00",
            "Stress matrix provider credit",
        )
        workflow = create_provider_workflow(project, model.name)
        before = _counts()

        start = RunService(node_registry=registry(adapter)).start_run(workflow.name)
        executor = WorkflowExecutor(node_registry=registry(adapter))
        executor.run(start.workflow_run)
        executor.run(start.workflow_run)
        provider_job = _provider_job_for_run(start.workflow_run)

        first_poll = poll_provider_job(provider_job, provider_registry=ProviderRegistry([adapter]))
        second_poll = poll_provider_job(provider_job, provider_registry=ProviderRegistry([adapter]))
        batch = poll_pending_provider_jobs(provider=adapter.provider_name, provider_registry=ProviderRegistry([adapter]))
        resume_workflow(start.workflow_run)
        resume_workflow(start.workflow_run)

        self.assertEqual(first_poll["status"], "SUCCEEDED")
        self.assertEqual(second_poll["status"], "SUCCEEDED")
        self.assertEqual(batch["polled"], [])
        self.assertEqual(adapter.submitted, [provider_job])
        self.assertEqual(adapter.polled, [provider_job])
        self.assertEqual(frappe.db.count("AI Provider Job", {"node_run": ["in", list(start.node_runs)]}), 1)
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job}), 2)
        self.assertEqual(frappe.db.count("AI Credit Ledger", {"provider_job": provider_job, "ledger_type": "DEBIT"}), 1)
        self.assertEqual(ledger_counts(start.workflow_run).get("RESERVE"), 1)
        self.assertEqual(ledger_counts(start.workflow_run).get("RELEASE"), 1)
        self.assertEqual(ledger_counts(start.workflow_run).get("DEBIT"), 1)
        self.assertEqual(frappe.db.get_value("AI Workflow Run", start.workflow_run, "status"), "SUCCEEDED")
        _assert_counts_delta(
            self,
            before,
            {
                "AI Workflow Version": 1,
                "AI Workflow Run": 1,
                "AI Node Run": 3,
                "AI Provider Job": 1,
                "AI Asset": 2,
                "AI Credit Ledger": 3,
            },
        )

    def test_repeated_cancel_archive_share_and_denied_attempts_are_bounded(self):
        frappe.set_user(self.user)
        cancellable = create_text_tool_run(self.user, title="Stress Cancellable Run")
        add_member(cancellable["project"].name, self.viewer, "VIEWER")

        frappe.set_user(self.viewer)
        before_denied = _counts()
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.public_tools.cancel_my_run", workflow_run=cancellable["run"]["workflow_run"])
        _assert_counts_delta(self, before_denied, {})

        frappe.set_user(self.user)
        before_cancel = _counts()
        cancelled = frappe.call("slow_ai.api.public_tools.cancel_my_run", workflow_run=cancellable["run"]["workflow_run"])
        with self.assertRaises(frappe.ValidationError):
            frappe.call("slow_ai.api.public_tools.cancel_my_run", workflow_run=cancellable["run"]["workflow_run"])
        _safe_payload(self, cancelled)
        self.assertEqual(cancelled["run"]["status"], "CANCELLED")
        _assert_counts_delta(self, before_cancel, {})

        shareable = create_shareable_asset_run(self.user, title="Stress Shareable Run")
        before_share = _counts()
        first_share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=shareable["run"]["workflow_run"],
            selected_assets=[shareable["asset"].name],
        )
        second_share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=shareable["run"]["workflow_run"],
            selected_assets=[shareable["asset"].name],
        )
        self.assertEqual(first_share["share"]["name"], second_share["share"]["name"])
        _assert_counts_delta(self, before_share, {"AI Tool Run Share": 1})

        before_archive = _counts()
        archived = frappe.call("slow_ai.api.public_tools.archive_my_run", workflow_run=shareable["run"]["workflow_run"])
        repeated_archive = frappe.call(
            "slow_ai.api.public_tools.archive_my_run",
            workflow_run=shareable["run"]["workflow_run"],
        )
        _safe_payload(self, archived)
        _safe_payload(self, repeated_archive)
        self.assertEqual(archived["run"]["is_archived"], 1)
        self.assertEqual(repeated_archive["run"]["is_archived"], 1)
        _assert_counts_delta(self, before_archive, {})

    def test_repeated_rerun_prepare_and_recovery_paths_follow_current_policy(self):
        frappe.set_user(self.user)
        source = create_text_tool_run(self.user, title="Stress Rerun Source")
        run_workflow(source["run"]["workflow_run"])
        before_rerun = _counts()

        first_rerun = frappe.call(
            "slow_ai.api.public_tools.prepare_rerun_from_run",
            workflow_run=source["run"]["workflow_run"],
        )
        second_rerun = frappe.call(
            "slow_ai.api.public_tools.prepare_rerun_from_run",
            workflow_run=source["run"]["workflow_run"],
        )

        self.assertNotEqual(first_rerun["workflow"]["name"], second_rerun["workflow"]["name"])
        self.assertEqual(
            first_rerun["workflow"]["source_template_version"],
            source["workflow"]["source_template_version"],
        )
        self.assertEqual(
            second_rerun["workflow"]["source_template_version"],
            source["workflow"]["source_template_version"],
        )
        _assert_counts_delta(self, before_rerun, {"AI Workflow": 2})

        frappe.set_user("Administrator")
        _, _, active_start, _, _ = _make_provider_waiting_run()
        before_recovery_read = _counts()
        inspected = inspect_run_recovery(active_start.workflow_run, max_age_minutes=0)
        resumed = resume_run(active_start.workflow_run)
        resumed_again = resume_run(active_start.workflow_run)
        _assert_counts_delta(self, before_recovery_read, {})
        self.assertEqual(resumed["queue_job_id"], f"slow_ai:workflow_run:{active_start.workflow_run}")
        self.assertEqual(resumed_again["queue_job_id"], f"slow_ai:workflow_run:{active_start.workflow_run}")
        _safe_payload(self, inspected)
        _safe_payload(self, resumed)
        _safe_payload(self, resumed_again)

        before_expire = _counts()
        expired = expire_stuck_run(active_start.workflow_run, max_age_minutes=0, reason="Stress expiry")
        repeated_expire = expire_stuck_run(active_start.workflow_run, max_age_minutes=0, reason="Stress expiry")
        _safe_payload(self, expired)
        _safe_payload(self, repeated_expire)
        self.assertEqual(expired["run"]["status"], "EXPIRED")
        self.assertEqual(repeated_expire["run"]["status"], "EXPIRED")
        _assert_counts_delta(self, before_expire, {"AI Credit Ledger": 1})
        self.assertEqual(ledger_counts(active_start.workflow_run).get("RESERVE"), 1)
        self.assertEqual(ledger_counts(active_start.workflow_run).get("RELEASE"), 1)

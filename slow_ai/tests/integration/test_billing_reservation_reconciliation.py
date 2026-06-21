import json
from decimal import Decimal

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.billing import get_balance
from slow_ai.application.run_service import RunService
from slow_ai.domain.status import NodeRunStatus, ProviderJobStatus, WorkflowRunStatus
from slow_ai.engine.executor import WorkflowExecutor
from slow_ai.infrastructure.repositories import FrappeEngineRepository
from slow_ai.providers.registry import ProviderRegistry
from slow_ai.tests.integration.test_billing_credit_reservation import ledger_counts
from slow_ai.tests.integration.test_billing_credit_reservation import provider_job_for_run
from slow_ai.tests.integration.test_billing_credit_reservation import registry
from slow_ai.tests.integration.test_billing_credit_reservation import setup_provider_run
from slow_ai.workers.poll_provider_job import poll_provider_job


UNSAFE_FRAGMENTS = (
    "reservation-provider-secret",
    "raw-failure-secret",
    "request_json",
    "response_json",
    "raw_error_json",
    "provider_account",
    "api_key",
    "Authorization",
    "Bearer",
    "Traceback",
    "https://provider.example.invalid",
)


def _prompt_node_run(workflow_run: str) -> str:
    return frappe.db.get_value(
        "AI Node Run",
        {"workflow_run": workflow_run, "node_id": "prompt_1"},
        "name",
    )


def _active_reservation_count(workflow_run: str) -> int:
    reservations = frappe.get_all(
        "AI Credit Ledger",
        filters={"workflow_run": workflow_run, "ledger_type": "RESERVE"},
        pluck="name",
    )
    active = 0
    for reservation in reservations:
        if not frappe.db.exists(
            "AI Credit Ledger",
            {
                "ledger_type": "RELEASE",
                "reference_doctype": "AI Credit Ledger",
                "reference_name": reservation,
            },
        ):
            active += 1
    return active


def _assert_safe_payload(testcase: FrappeTestCase, payload):
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


class TestBillingReservationReconciliation(FrappeTestCase):
    def tearDown(self):
        frappe.set_user("Administrator")

    def test_success_with_missing_actual_cost_uses_estimate_and_reconciles_once(self):
        project, workflow, adapter = setup_provider_run(amount_usd="0.10", poll_cost_usd=0.0)
        result = WorkflowExecutor(node_registry=registry(adapter))
        start = RunService().start_run(workflow.name)
        result.run(start.workflow_run)
        provider_job = provider_job_for_run(start.workflow_run)

        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        provider_job.reload()
        counts = ledger_counts(start.workflow_run)
        self.assertEqual(counts.get("RESERVE"), 1)
        self.assertEqual(counts.get("RELEASE"), 1)
        self.assertEqual(counts.get("DEBIT"), 1)
        self.assertEqual(provider_job.debit_cost_source, "ESTIMATED")
        self.assertEqual(Decimal(str(provider_job.debit_cost_usd)), Decimal("0.1000"))
        self.assertEqual(_active_reservation_count(start.workflow_run), 0)
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("0.90"))

    def test_zero_cost_success_creates_asset_without_reserve_or_debit(self):
        project, workflow, adapter = setup_provider_run(amount_usd="0.00", poll_cost_usd=0.0)
        start = RunService().start_run(workflow.name)
        WorkflowExecutor(node_registry=registry(adapter)).run(start.workflow_run)
        provider_job = provider_job_for_run(start.workflow_run)

        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        provider_job.reload()
        counts = ledger_counts(start.workflow_run)
        self.assertIsNone(counts.get("RESERVE"))
        self.assertIsNone(counts.get("RELEASE"))
        self.assertIsNone(counts.get("DEBIT"))
        self.assertEqual(provider_job.debit_cost_source, "ZERO_COST")
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job.name}), 1)
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("1.00"))

    def test_node_failure_before_provider_job_releases_reservation_without_provider_side_effects(self):
        project, workflow, adapter = setup_provider_run()
        start = RunService().start_run(workflow.name)
        prompt_node = _prompt_node_run(start.workflow_run)
        repository = FrappeEngineRepository()

        repository.set_node_status(
            prompt_node,
            NodeRunStatus.FAILED,
            error={"type": "TestNodeFailure", "message": "Node failed before provider submission."},
        )
        repository.set_workflow_status(
            start.workflow_run,
            WorkflowRunStatus.FAILED,
            {"type": "TestNodeFailure", "message": "Workflow failed before provider submission."},
        )
        repository.set_workflow_status(
            start.workflow_run,
            WorkflowRunStatus.FAILED,
            {"type": "TestNodeFailure", "message": "Workflow failed before provider submission."},
        )

        counts = ledger_counts(start.workflow_run)
        self.assertEqual(counts.get("RESERVE"), 1)
        self.assertEqual(counts.get("RELEASE"), 1)
        self.assertIsNone(counts.get("DEBIT"))
        self.assertEqual(_active_reservation_count(start.workflow_run), 0)
        self.assertFalse(frappe.db.exists("AI Provider Job", {"provider": adapter.provider_name}))
        self.assertFalse(frappe.db.exists("AI Asset", {"source_workflow_run": start.workflow_run}))
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("1.00"))

    def test_cancellation_before_provider_submission_releases_reservation_once(self):
        project, workflow, adapter = setup_provider_run()
        start = RunService().start_run(workflow.name)

        cancelled = frappe.call("slow_ai.api.public_tools.cancel_my_run", workflow_run=start.workflow_run)
        with self.assertRaises(frappe.ValidationError):
            frappe.call("slow_ai.api.public_tools.cancel_my_run", workflow_run=start.workflow_run)

        counts = ledger_counts(start.workflow_run)
        self.assertEqual(cancelled["run"]["status"], "CANCELLED")
        self.assertEqual(counts.get("RESERVE"), 1)
        self.assertEqual(counts.get("RELEASE"), 1)
        self.assertIsNone(counts.get("DEBIT"))
        self.assertEqual(_active_reservation_count(start.workflow_run), 0)
        self.assertFalse(frappe.db.exists("AI Provider Job", {"provider": adapter.provider_name}))
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("1.00"))

    def test_cancellation_while_waiting_provider_releases_and_poller_noops(self):
        project, workflow, adapter = setup_provider_run()
        start = RunService().start_run(workflow.name)
        WorkflowExecutor(node_registry=registry(adapter)).run(start.workflow_run)
        provider_job = provider_job_for_run(start.workflow_run)

        frappe.call("slow_ai.api.public_tools.cancel_my_run", workflow_run=start.workflow_run)
        polled = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        counts = ledger_counts(start.workflow_run)
        self.assertEqual(polled["status"], "CANCELLED")
        self.assertEqual(counts.get("RESERVE"), 1)
        self.assertEqual(counts.get("RELEASE"), 1)
        self.assertIsNone(counts.get("DEBIT"))
        self.assertEqual(_active_reservation_count(start.workflow_run), 0)
        self.assertFalse(frappe.db.exists("AI Asset", {"source_provider_job": provider_job.name}))
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("1.00"))

    def test_provider_expiry_or_retry_exhaustion_releases_reservation_once(self):
        project, workflow, adapter = setup_provider_run(poll_status=ProviderJobStatus.WAITING_PROVIDER.value)
        start = RunService().start_run(workflow.name)
        WorkflowExecutor(node_registry=registry(adapter)).run(start.workflow_run)
        provider_job = provider_job_for_run(start.workflow_run)
        frappe.db.set_value("AI Provider Job", provider_job.name, {"max_poll_attempts": 1, "poll_attempts": 0})

        first = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        second = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        counts = ledger_counts(start.workflow_run)
        self.assertEqual(first["status"], "EXPIRED")
        self.assertEqual(second["status"], "EXPIRED")
        self.assertEqual(counts.get("RESERVE"), 1)
        self.assertEqual(counts.get("RELEASE"), 1)
        self.assertIsNone(counts.get("DEBIT"))
        self.assertEqual(_active_reservation_count(start.workflow_run), 0)
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("1.00"))

    def test_read_apis_do_not_reconcile_or_release_active_reservations(self):
        project, workflow, adapter = setup_provider_run()
        start = RunService().start_run(workflow.name)
        before_counts = ledger_counts(start.workflow_run)

        payloads = [
            frappe.call("slow_ai.api.billing.get_balance", project=project.name),
            frappe.call("slow_ai.api.billing.get_ledger", project=project.name),
            frappe.call("slow_ai.api.runs.get_run_status", workflow_run=start.workflow_run),
            frappe.call("slow_ai.api.runs.get_history", workflow_run=start.workflow_run),
            frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=start.workflow_run),
        ]

        self.assertEqual(before_counts.get("RESERVE"), 1)
        self.assertEqual(ledger_counts(start.workflow_run), before_counts)
        self.assertEqual(_active_reservation_count(start.workflow_run), 1)
        self.assertFalse(frappe.db.exists("AI Provider Job", {"provider": adapter.provider_name}))
        for payload in payloads:
            _assert_safe_payload(self, payload)

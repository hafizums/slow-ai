import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from slow_ai.application.runs import get_history, get_run_status, get_run_timeline
from slow_ai.application.run_service import RunService
from slow_ai.domain.status import ProviderJobStatus
from slow_ai.engine.executor import WorkflowExecutor
from slow_ai.providers.registry import ProviderRegistry
from slow_ai.tests.integration.test_billing_credit_reservation import ledger_counts
from slow_ai.tests.integration.test_billing_credit_reservation import provider_job_for_run
from slow_ai.tests.integration.test_billing_credit_reservation import registry as reservation_registry
from slow_ai.tests.integration.test_billing_credit_reservation import setup_provider_run
from slow_ai.tests.integration.test_provider_job_timeout_retry_policy import WaitingProviderAdapter
from slow_ai.tests.integration.test_provider_job_timeout_retry_policy import create_waiting_run
from slow_ai.workers.poll_provider_job import poll_pending_provider_jobs, poll_provider_job


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
    "retry-provider-secret",
    "raw-timeout-secret",
    "raw-failure-secret",
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


def _safe_payload(testcase: FrappeTestCase, payload) -> None:
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


class TestProviderJobRetryBackoffMatrix(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_waiting_provider_job_polls_once_when_eligible(self):
        adapter = WaitingProviderAdapter()
        _, _, result, _, provider_job = create_waiting_run(adapter)

        polled = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        provider_job.reload()
        self.assertEqual(polled["status"], "WAITING_PROVIDER")
        self.assertEqual(polled["queue_job_id"], None)
        self.assertEqual(adapter.polled, [provider_job.name])
        self.assertEqual(provider_job.poll_attempts, 1)
        self.assertTrue(provider_job.last_polled_at)
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job.name}), 0)
        self.assertIsNone(ledger_counts(result.workflow_run).get("DEBIT"))
        self.assertIsNone(ledger_counts(result.workflow_run).get("RELEASE"))

    def test_current_policy_has_no_time_backoff_and_keeps_attempts_bounded(self):
        adapter = WaitingProviderAdapter()
        _, _, _, _, provider_job = create_waiting_run(adapter)
        frappe.db.set_value("AI Provider Job", provider_job.name, {"max_poll_attempts": 3, "poll_attempts": 0})

        first = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        second = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        provider_job.reload()
        self.assertEqual(first["status"], "WAITING_PROVIDER")
        self.assertEqual(second["status"], "WAITING_PROVIDER")
        self.assertEqual(adapter.polled, [provider_job.name, provider_job.name])
        self.assertEqual(provider_job.poll_attempts, 2)
        self.assertEqual(provider_job.max_poll_attempts, 3)

    def test_timeout_and_max_attempt_expiry_are_idempotent_and_do_not_resume(self):
        adapter = WaitingProviderAdapter()
        _, _, timeout_run, _, timeout_job = create_waiting_run(adapter)
        old_submitted_at = add_to_date(now_datetime(), seconds=-120)
        frappe.db.set_value(
            "AI Provider Job",
            timeout_job.name,
            {"submitted_at": old_submitted_at, "timeout_seconds": 1, "poll_attempts": 0},
        )

        timeout_first = poll_provider_job(timeout_job.name, provider_registry=ProviderRegistry([adapter]))
        timeout_second = poll_provider_job(timeout_job.name, provider_registry=ProviderRegistry([adapter]))

        self.assertEqual(timeout_first["status"], "EXPIRED")
        self.assertEqual(timeout_second["status"], "EXPIRED")
        self.assertEqual(timeout_first["queue_job_id"], None)
        self.assertEqual(timeout_second["queue_job_id"], None)
        self.assertEqual(frappe.db.get_value("AI Provider Job", timeout_job.name, "poll_attempts"), 0)
        self.assertEqual(ledger_counts(timeout_run.workflow_run).get("RESERVE"), 1)
        self.assertEqual(ledger_counts(timeout_run.workflow_run).get("RELEASE"), 1)

        max_adapter = WaitingProviderAdapter()
        _, _, max_run, _, max_job = create_waiting_run(max_adapter)
        frappe.db.set_value("AI Provider Job", max_job.name, {"max_poll_attempts": 1, "poll_attempts": 0})

        max_first = poll_provider_job(max_job.name, provider_registry=ProviderRegistry([max_adapter]))
        max_second = poll_provider_job(max_job.name, provider_registry=ProviderRegistry([max_adapter]))

        self.assertEqual(max_first["status"], "EXPIRED")
        self.assertEqual(max_second["status"], "EXPIRED")
        self.assertEqual(max_adapter.polled, [max_job.name])
        self.assertEqual(ledger_counts(max_run.workflow_run).get("RESERVE"), 1)
        self.assertEqual(ledger_counts(max_run.workflow_run).get("RELEASE"), 1)
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": max_job.name}), 0)
        self.assertIsNone(ledger_counts(max_run.workflow_run).get("DEBIT"))

    def test_automatic_retry_is_disabled_even_when_retry_metadata_exists(self):
        _, workflow, adapter = setup_provider_run(poll_status=ProviderJobStatus.FAILED.value)
        result = RunService(node_registry=reservation_registry(adapter)).start_run(workflow.name)
        WorkflowExecutor(node_registry=reservation_registry(adapter)).run(result.workflow_run)
        provider_job = provider_job_for_run(result.workflow_run)
        frappe.db.set_value(
            "AI Provider Job",
            provider_job.name,
            {
                "retry_count": 0,
                "max_retries": 2,
                "request_json": json.dumps({"Authorization": f"Bearer {_unique('retry-provider-secret')}"}),
            },
        )

        first = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        second = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        provider_job.reload()
        self.assertEqual(first["status"], "FAILED")
        self.assertEqual(second["status"], "FAILED")
        self.assertEqual(provider_job.retry_count, 0)
        self.assertEqual(provider_job.max_retries, 2)
        self.assertEqual(frappe.db.count("AI Provider Job", {"node_run": provider_job.node_run}), 1)
        self.assertEqual(adapter.polled, [provider_job.name])
        self.assertEqual(ledger_counts(result.workflow_run).get("RESERVE"), 1)
        self.assertEqual(ledger_counts(result.workflow_run).get("RELEASE"), 1)
        self.assertIsNone(ledger_counts(result.workflow_run).get("DEBIT"))

    def test_cancellation_wins_over_retry_timeout_and_pending_batch_poll(self):
        adapter = WaitingProviderAdapter()
        _, _, result, node_run, provider_job = create_waiting_run(adapter)
        frappe.db.set_value("AI Workflow Run", result.workflow_run, "status", "CANCELLED")
        frappe.db.set_value(
            "AI Provider Job",
            provider_job.name,
            {"timeout_seconds": 0, "max_poll_attempts": 0, "retry_count": 0, "max_retries": 9},
        )

        direct = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        batch = poll_pending_provider_jobs(provider=adapter.provider_name, provider_registry=ProviderRegistry([adapter]))

        self.assertEqual(direct["status"], "CANCELLED")
        self.assertEqual(batch["polled"], [])
        self.assertEqual(batch["skipped"], [])
        self.assertEqual(adapter.polled, [])
        self.assertEqual(frappe.db.get_value("AI Workflow Run", result.workflow_run, "status"), "CANCELLED")
        self.assertEqual(frappe.db.get_value("AI Node Run", node_run, "status"), "CANCELLED")
        self.assertEqual(frappe.db.get_value("AI Provider Job", provider_job.name, "status"), "CANCELLED")

    def test_terminal_jobs_are_not_repolled_and_safe_payloads_remain_redacted(self):
        _, workflow, adapter = setup_provider_run()
        result = RunService(node_registry=reservation_registry(adapter)).start_run(workflow.name)
        WorkflowExecutor(node_registry=reservation_registry(adapter)).run(result.workflow_run)
        provider_job = provider_job_for_run(result.workflow_run)
        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        before = _counts()
        secret = _unique("retry-provider-secret")
        frappe.db.set_value(
            "AI Provider Job",
            provider_job.name,
            {
                "request_json": json.dumps({"Authorization": f"Bearer {secret}"}),
                "response_json": json.dumps({"raw_provider_url": "https://provider.example.invalid/output.png"}),
                "raw_error_json": json.dumps({"api_key": secret}),
            },
        )

        repeated = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        status = get_run_status(result.workflow_run)
        history = get_history(result.workflow_run)
        timeline = get_run_timeline(result.workflow_run)

        self.assertEqual(repeated["status"], "SUCCEEDED")
        self.assertEqual(adapter.polled, [provider_job.name])
        self.assertEqual(_counts(), before)
        _safe_payload(self, status)
        _safe_payload(self, history)
        _safe_payload(self, timeline)

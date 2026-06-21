import json
from decimal import Decimal
from typing import Any, Mapping
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.billing import create_top_up, get_balance
from slow_ai.application.run_service import RunService
from slow_ai.domain.exceptions import RunPreflightError
from slow_ai.domain.status import ProviderJobStatus
from slow_ai.engine.executor import WorkflowExecutor
from slow_ai.infrastructure.provider_jobs import ProviderJobRepository
from slow_ai.node_registry.nodes.export_output import ExportOutputNode
from slow_ai.node_registry.nodes.provider import ProviderTextToImageNode
from slow_ai.node_registry.nodes.text_prompt import TextPromptNode
from slow_ai.node_registry.registry import NodeRegistry
from slow_ai.providers.contracts import (
    NormalizedProviderOutput,
    NormalizedProviderResult,
    ProviderAdapter,
    ProviderSubmission,
)
from slow_ai.providers.registry import ProviderRegistry
from slow_ai.workers.poll_provider_job import poll_provider_job


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Reservation Project"),
            "status": "Open",
        }
    )


def create_model(provider: str, amount_usd: str = "0.10"):
    return insert_doc(
        {
            "doctype": "AI Model",
            "model_id": unique(f"{provider}/model"),
            "model_name": "Reservation Test Model",
            "provider": provider,
            "status": "ENABLED",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "amount_usd": amount_usd}),
        }
    )


def create_provider_account(provider: str):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("Reservation Provider Account"),
            "api_key_secret": "reservation-provider-secret",
            "is_default": 1,
            "status": "ACTIVE",
        }
    )


def create_provider_workflow(project, provider: str, model_name: str):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Reservation Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Reservation prompt"}},
                    {
                        "id": "provider_1",
                        "type": "provider_text_to_image",
                        "config": {"provider": provider, "model": model_name},
                    },
                    {"id": "output_1", "type": "export_output", "config": {}},
                ]
            ),
            "draft_edges_json": json.dumps(
                [
                    {
                        "id": "edge_1",
                        "source": "prompt_1",
                        "source_port": "text",
                        "target": "provider_1",
                        "target_port": "prompt",
                    },
                    {
                        "id": "edge_2",
                        "source": "provider_1",
                        "source_port": "image",
                        "target": "output_1",
                        "target_port": "image",
                    },
                ]
            ),
            "layout_json": json.dumps({"nodes": []}),
        }
    )


class ReservationProviderAdapter(ProviderAdapter):
    def __init__(
        self,
        *,
        provider_name: str,
        poll_status: str = ProviderJobStatus.SUCCEEDED.value,
        poll_cost_usd: float = 0.07,
    ) -> None:
        self.provider_name = provider_name
        self.poll_status = poll_status
        self.poll_cost_usd = poll_cost_usd
        self.provider_jobs = ProviderJobRepository()
        self.submitted: list[str] = []
        self.polled: list[str] = []

    def submit_job(self, submission: ProviderSubmission) -> NormalizedProviderResult:
        self.submitted.append(submission.provider_job_name)
        self.provider_jobs.mark_submitting(submission.provider_job_name)
        result = NormalizedProviderResult(
            status=ProviderJobStatus.WAITING_PROVIDER.value,
            external_job_id=f"{self.provider_name}-external",
        )
        self.provider_jobs.apply_result(
            submission.provider_job_name,
            result,
            {"data": {"id": f"{self.provider_name}-external", "status": "processing"}},
        )
        return result

    def poll_job(self, provider_job_name: str) -> NormalizedProviderResult:
        self.polled.append(provider_job_name)
        if self.poll_status == ProviderJobStatus.SUCCEEDED.value:
            result = NormalizedProviderResult(
                status=ProviderJobStatus.SUCCEEDED.value,
                external_job_id=f"{self.provider_name}-external",
                outputs=(
                    NormalizedProviderOutput(
                        asset_type="IMAGE",
                        url="https://example.invalid/reservation-output.png",
                        mime_type="image/png",
                        metadata={},
                    ),
                ),
                cost_usd=self.poll_cost_usd,
            )
            raw_response = {"data": {"status": "completed", "output": "https://example.invalid/reservation-output.png"}}
        elif self.poll_status == ProviderJobStatus.FAILED.value:
            result = NormalizedProviderResult(
                status=ProviderJobStatus.FAILED.value,
                external_job_id=f"{self.provider_name}-external",
                error={"message": "Provider failed safely."},
            )
            raw_response = {"data": {"status": "failed", "secret": "raw-failure-secret"}}
        else:
            result = NormalizedProviderResult(
                status=ProviderJobStatus.WAITING_PROVIDER.value,
                external_job_id=f"{self.provider_name}-external",
            )
            raw_response = {"data": {"status": "processing"}}
        self.provider_jobs.apply_result(provider_job_name, result, raw_response)
        return result

    def cancel_job(self, provider_job_name: str) -> None:
        self.provider_jobs.mark_cancelled(provider_job_name)

    def normalize_result(self, raw_response: Mapping[str, Any]) -> NormalizedProviderResult:
        status = (raw_response.get("data") or {}).get("status")
        if status == "completed":
            return NormalizedProviderResult(status=ProviderJobStatus.SUCCEEDED.value)
        if status == "failed":
            return NormalizedProviderResult(status=ProviderJobStatus.FAILED.value)
        return NormalizedProviderResult(status=ProviderJobStatus.WAITING_PROVIDER.value)

    def estimate_cost(self, model: str, input_data: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"currency": "USD", "estimated_cost_usd": 0.10, "model": model}


def registry(adapter: ReservationProviderAdapter) -> NodeRegistry:
    return NodeRegistry(
        [
            TextPromptNode(),
            ProviderTextToImageNode(provider_registry=ProviderRegistry([adapter])),
            ExportOutputNode(),
        ]
    )


def setup_provider_run(
    *,
    amount_usd: str = "0.10",
    top_up_usd: str = "1.00",
    poll_status: str = ProviderJobStatus.SUCCEEDED.value,
    poll_cost_usd: float = 0.07,
):
    provider = unique("reservation-provider")
    adapter = ReservationProviderAdapter(
        provider_name=provider,
        poll_status=poll_status,
        poll_cost_usd=poll_cost_usd,
    )
    project = create_project()
    model = create_model(provider, amount_usd)
    create_provider_account(provider)
    create_top_up(project.name, top_up_usd, "Reservation test credit")
    workflow = create_provider_workflow(project, provider, model.name)
    return project, workflow, adapter


def provider_job_for_run(workflow_run: str):
    node_runs = frappe.get_all("AI Node Run", filters={"workflow_run": workflow_run}, pluck="name")
    return frappe.get_doc("AI Provider Job", frappe.db.get_value("AI Provider Job", {"node_run": ["in", node_runs]}, "name"))


def ledger_counts(workflow_run: str) -> dict[str, int]:
    rows = frappe.get_all(
        "AI Credit Ledger",
        filters={"workflow_run": workflow_run},
        fields=["ledger_type"],
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.ledger_type] = counts.get(row.ledger_type, 0) + 1
    return counts


class TestBillingCreditReservation(FrappeTestCase):
    def test_insufficient_balance_rejects_before_run_and_reservation_records(self):
        provider = unique("reservation-low-provider")
        project = create_project()
        model = create_model(provider, "0.10")
        create_provider_account(provider)
        create_top_up(project.name, "0.04", "Low reservation credit")
        workflow = create_provider_workflow(project, provider, model.name)
        version_count = frappe.db.count("AI Workflow Version", {"workflow": workflow.name})
        run_count = frappe.db.count("AI Workflow Run", {"workflow": workflow.name})
        provider_job_count = frappe.db.count("AI Provider Job", {"provider": provider})
        reservation_count = frappe.db.count("AI Credit Ledger", {"project": project.name, "ledger_type": "RESERVE"})

        with self.assertRaises(RunPreflightError):
            RunService().start_run(workflow.name)

        self.assertEqual(frappe.db.count("AI Workflow Version", {"workflow": workflow.name}), version_count)
        self.assertEqual(frappe.db.count("AI Workflow Run", {"workflow": workflow.name}), run_count)
        self.assertEqual(frappe.db.count("AI Provider Job", {"provider": provider}), provider_job_count)
        self.assertEqual(
            frappe.db.count("AI Credit Ledger", {"project": project.name, "ledger_type": "RESERVE"}),
            reservation_count,
        )

    def test_start_run_creates_one_reservation_and_duplicate_start_does_not_duplicate(self):
        project, workflow, adapter = setup_provider_run()

        first = RunService(node_registry=registry(adapter)).start_run(workflow.name)
        second = RunService(node_registry=registry(adapter)).start_run(workflow.name)

        self.assertEqual(first.workflow_run, second.workflow_run)
        reservations = frappe.get_all(
            "AI Credit Ledger",
            filters={"workflow_run": first.workflow_run, "ledger_type": "RESERVE"},
            fields=["name", "amount_usd", "node_run", "provider_job", "metadata_json"],
        )
        self.assertEqual(len(reservations), 1)
        self.assertEqual(float(reservations[0].amount_usd), 0.10)
        self.assertTrue(reservations[0].node_run)
        self.assertFalse(reservations[0].provider_job)
        self.assertIn(adapter.provider_name, reservations[0].metadata_json)
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("0.90"))

        WorkflowExecutor(node_registry=registry(adapter)).run(first.workflow_run)
        provider_job = provider_job_for_run(first.workflow_run)
        reservation = frappe.get_doc("AI Credit Ledger", reservations[0].name)
        reservation_metadata = json.loads(reservation.metadata_json)
        self.assertFalse(reservation.provider_job)
        self.assertEqual(reservation_metadata["provider_job"], provider_job.name)
        self.assertEqual(ledger_counts(first.workflow_run).get("RESERVE"), 1)

    def test_provider_success_debits_and_releases_reservation_idempotently(self):
        project, workflow, adapter = setup_provider_run(poll_cost_usd=0.07)
        result = RunService(node_registry=registry(adapter)).start_run(workflow.name)
        WorkflowExecutor(node_registry=registry(adapter)).run(result.workflow_run)
        provider_job = provider_job_for_run(result.workflow_run)

        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        counts = ledger_counts(result.workflow_run)
        self.assertEqual(counts.get("RESERVE"), 1)
        self.assertEqual(counts.get("RELEASE"), 1)
        self.assertEqual(counts.get("DEBIT"), 1)
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job.name}), 1)
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("0.93"))

    def test_provider_failure_releases_reservation_without_output_asset(self):
        project, workflow, adapter = setup_provider_run(poll_status=ProviderJobStatus.FAILED.value)
        result = RunService(node_registry=registry(adapter)).start_run(workflow.name)
        WorkflowExecutor(node_registry=registry(adapter)).run(result.workflow_run)
        provider_job = provider_job_for_run(result.workflow_run)

        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        counts = ledger_counts(result.workflow_run)
        self.assertEqual(counts.get("RESERVE"), 1)
        self.assertEqual(counts.get("RELEASE"), 1)
        self.assertIsNone(counts.get("DEBIT"))
        self.assertFalse(frappe.db.exists("AI Asset", {"source_provider_job": provider_job.name}))
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("1.00"))

    def test_provider_timeout_releases_reservation_idempotently(self):
        project, workflow, adapter = setup_provider_run(poll_status=ProviderJobStatus.WAITING_PROVIDER.value)
        result = RunService(node_registry=registry(adapter)).start_run(workflow.name)
        WorkflowExecutor(node_registry=registry(adapter)).run(result.workflow_run)
        provider_job = provider_job_for_run(result.workflow_run)
        frappe.db.set_value("AI Provider Job", provider_job.name, {"max_poll_attempts": 1, "poll_attempts": 0})

        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        counts = ledger_counts(result.workflow_run)
        self.assertEqual(frappe.get_doc("AI Provider Job", provider_job.name).status, "EXPIRED")
        self.assertEqual(counts.get("RESERVE"), 1)
        self.assertEqual(counts.get("RELEASE"), 1)
        self.assertIsNone(counts.get("DEBIT"))
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("1.00"))

    def test_user_cancellation_releases_reservation_idempotently(self):
        project, workflow, adapter = setup_provider_run()
        result = RunService(node_registry=registry(adapter)).start_run(workflow.name)
        WorkflowExecutor(node_registry=registry(adapter)).run(result.workflow_run)

        first = frappe.call("slow_ai.api.public_tools.cancel_my_run", workflow_run=result.workflow_run)
        with self.assertRaises(frappe.ValidationError):
            frappe.call("slow_ai.api.public_tools.cancel_my_run", workflow_run=result.workflow_run)

        self.assertEqual(first["run"]["status"], "CANCELLED")
        counts = ledger_counts(result.workflow_run)
        self.assertEqual(counts.get("RESERVE"), 1)
        self.assertEqual(counts.get("RELEASE"), 1)
        self.assertIsNone(counts.get("DEBIT"))
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("1.00"))

    def test_public_run_detail_shows_safe_reservation_cost_summary(self):
        _, workflow, adapter = setup_provider_run(poll_cost_usd=0.07)
        result = RunService(node_registry=registry(adapter)).start_run(workflow.name)
        WorkflowExecutor(node_registry=registry(adapter)).run(result.workflow_run)
        provider_job = provider_job_for_run(result.workflow_run)
        frappe.db.set_value(
            "AI Provider Job",
            provider_job.name,
            {
                "response_json": json.dumps({"Authorization": "Bearer secret-reservation-token"}),
                "raw_error_json": json.dumps({"message": "token=secret-reservation-token"}),
            },
        )

        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        payload = frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=result.workflow_run)
        encoded = json.dumps(payload, default=str)

        self.assertEqual(Decimal(payload["cost_summary"]["reserved_usd"]), Decimal("0.10"))
        self.assertEqual(Decimal(payload["cost_summary"]["released_usd"]), Decimal("0.10"))
        self.assertEqual(Decimal(payload["cost_summary"]["debits_usd"]), Decimal("0.07"))
        self.assertNotIn("secret-reservation-token", encoded)
        self.assertNotIn("request_json", encoded)
        self.assertNotIn("response_json", encoded)
        self.assertNotIn("raw_error_json", encoded)
        self.assertNotIn("provider_account", encoded)

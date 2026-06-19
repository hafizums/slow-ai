import json
from decimal import Decimal
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.billing import create_top_up
from slow_ai.domain.exceptions import ProviderInvariantError, RunPreflightError
from slow_ai.infrastructure.provider_outputs import ProviderOutputService
from slow_ai.providers.contracts import NormalizedProviderOutput, NormalizedProviderResult


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Billing Project"),
            "status": "Open",
        }
    )


def create_provider_account(provider: str):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("Billing Provider Account"),
            "api_key_secret": "billing-test-secret",
            "is_default": 1,
            "status": "ACTIVE",
        }
    )


def create_model(provider: str, amount_usd: str = "0.10"):
    return insert_doc(
        {
            "doctype": "AI Model",
            "model_id": unique(f"{provider}/model"),
            "model_name": "Billing Test Model",
            "provider": provider,
            "status": "ENABLED",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "amount_usd": amount_usd}),
        }
    )


def create_provider_workflow(project, *, provider: str, model_name: str):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Billing Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Billing prompt"}},
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
            "layout_json": "{}",
        }
    )


def create_started_run(project):
    workflow = insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Billing History Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "History"}},
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
    )
    result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)
    node_run = frappe.db.get_value(
        "AI Node Run",
        {"workflow_run": result["workflow_run"], "node_id": "prompt_1"},
        "name",
    )
    return result["workflow_run"], node_run


class TestBillingCreditBalance(FrappeTestCase):
    def test_top_up_creates_real_credit_and_balance_uses_real_ledger_rows(self):
        project = create_project()

        top_up = frappe.call(
            "slow_ai.api.billing.create_top_up",
            project=project.name,
            amount_usd="1.25",
            description="Billing balance test top-up",
        )
        balance = frappe.call("slow_ai.api.billing.get_balance", project=project.name)
        ledger = frappe.call("slow_ai.api.billing.get_ledger", project=project.name)

        self.assertTrue(frappe.db.exists("AI Credit Ledger", top_up["ledger"]["name"]))
        self.assertEqual(top_up["ledger"]["ledger_type"], "CREDIT")
        self.assertEqual(Decimal(balance["balance_usd"]), Decimal("1.25"))
        self.assertEqual(Decimal(ledger["balance"]["credits_usd"]), Decimal("1.25"))
        self.assertIn(top_up["ledger"]["name"], {row["name"] for row in ledger["ledger"]})

    def test_provider_run_with_enough_balance_passes_preflight(self):
        provider = unique("billing-provider")
        project = create_project()
        model = create_model(provider, "0.10")
        create_provider_account(provider)
        create_top_up(project.name, "0.25", "Provider run credit")
        workflow = create_provider_workflow(project, provider=provider, model_name=model.name)

        result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertTrue(frappe.db.exists("AI Workflow Version", result["workflow_version"]))
        self.assertTrue(frappe.db.exists("AI Workflow Run", result["workflow_run"]))
        self.assertEqual(len(result["node_runs"]), 3)

    def test_provider_run_with_insufficient_balance_rejects_before_enqueue(self):
        provider = unique("billing-low-provider")
        project = create_project()
        model = create_model(provider, "0.10")
        create_provider_account(provider)
        create_top_up(project.name, "0.04", "Insufficient credit")
        workflow = create_provider_workflow(project, provider=provider, model_name=model.name)
        provider_job_count = frappe.db.count("AI Provider Job")

        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertIn("exceeds available project credit balance", str(exc.exception))
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)
        self.assertFalse(frappe.db.exists("AI Workflow Version", {"workflow": workflow.name}))
        self.assertFalse(frappe.db.exists("AI Workflow Run", {"workflow": workflow.name}))

    def test_provider_output_debit_is_idempotent_and_history_is_safe(self):
        project = create_project()
        workflow_run, node_run = create_started_run(project)
        model = create_model("billing_provider", "0.07")
        provider_job = insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run,
                "provider": "billing_provider",
                "model": model.name,
                "status": "SUCCEEDED",
                "idempotency_key": unique("billing-provider-job"),
                "estimated_cost_usd": 0.09,
                "request_json": json.dumps({"prompt": "Billing"}),
                "response_json": json.dumps({"status": "completed"}),
            }
        )
        result = NormalizedProviderResult(
            status="SUCCEEDED",
            external_job_id="billing-external-1",
            outputs=(
                NormalizedProviderOutput(
                    asset_type="IMAGE",
                    url="https://example.invalid/billing.png",
                    mime_type="image/png",
                    metadata={},
                ),
            ),
            cost_usd=0.07,
        )
        service = ProviderOutputService()

        first = service.materialize(
            project_name=project.name,
            workflow_run_name=workflow_run,
            node_run_name=node_run,
            provider_job_name=provider_job.name,
            result=result,
            description="Billing provider debit",
        )
        second = service.materialize(
            project_name=project.name,
            workflow_run_name=workflow_run,
            node_run_name=node_run,
            provider_job_name=provider_job.name,
            result=result,
            description="Billing provider debit",
        )
        history = frappe.call("slow_ai.api.runs.get_history", workflow_run=workflow_run)
        ledger = frappe.call("slow_ai.api.billing.get_ledger", project=project.name)

        ledger_names = frappe.get_all(
            "AI Credit Ledger",
            filters={"provider_job": provider_job.name, "ledger_type": "DEBIT"},
            pluck="name",
        )
        self.assertEqual(first.ledger_name, second.ledger_name)
        self.assertEqual(len(ledger_names), 1)
        debit_job = frappe.get_doc("AI Provider Job", provider_job.name)
        debit_ledger = frappe.get_doc("AI Credit Ledger", ledger_names[0])
        self.assertEqual(float(debit_ledger.amount_usd), 0.07)
        self.assertEqual(float(debit_job.debit_cost_usd), 0.07)
        self.assertEqual(debit_job.debit_cost_source, "ACTUAL")
        self.assertIn(first.ledger_name, {row["name"] for row in history["ledger"]})
        self.assertIn("debit_cost_source", history["provider_jobs"][0])
        self.assertIn(first.ledger_name, {row["name"] for row in ledger["ledger"]})
        serialized_ledger = json.dumps(ledger, default=str)
        self.assertNotIn("api_key_secret", serialized_ledger)
        self.assertNotIn("provider_account", serialized_ledger)

    def test_provider_output_uses_estimated_cost_when_actual_cost_is_missing(self):
        project = create_project()
        workflow_run, node_run = create_started_run(project)
        model = create_model("billing_estimate_provider", "0.08")
        provider_job = insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run,
                "provider": "billing_estimate_provider",
                "model": model.name,
                "status": "SUCCEEDED",
                "idempotency_key": unique("billing-estimate-job"),
                "estimated_cost_usd": 0.08,
                "request_json": json.dumps({"prompt": "Estimated"}),
                "response_json": json.dumps({"status": "completed"}),
            }
        )
        result = NormalizedProviderResult(
            status="SUCCEEDED",
            external_job_id="billing-estimate-1",
            outputs=(
                NormalizedProviderOutput(
                    asset_type="IMAGE",
                    url="https://example.invalid/estimated.png",
                    mime_type="image/png",
                    metadata={},
                ),
            ),
            cost_usd=0.0,
        )

        first = ProviderOutputService().materialize(
            project_name=project.name,
            workflow_run_name=workflow_run,
            node_run_name=node_run,
            provider_job_name=provider_job.name,
            result=result,
            description="Estimated provider debit",
        )
        second = ProviderOutputService().materialize(
            project_name=project.name,
            workflow_run_name=workflow_run,
            node_run_name=node_run,
            provider_job_name=provider_job.name,
            result=NormalizedProviderResult(
                status="SUCCEEDED",
                external_job_id="billing-estimate-1",
                outputs=result.outputs,
                cost_usd=0.01,
            ),
            description="Estimated provider debit",
        )

        ledger_names = frappe.get_all(
            "AI Credit Ledger",
            filters={"provider_job": provider_job.name, "ledger_type": "DEBIT"},
            pluck="name",
        )
        provider_job.reload()
        ledger = frappe.get_doc("AI Credit Ledger", ledger_names[0])
        history = frappe.call("slow_ai.api.runs.get_history", workflow_run=workflow_run)

        self.assertEqual(first.ledger_name, second.ledger_name)
        self.assertEqual(len(ledger_names), 1)
        self.assertEqual(float(ledger.amount_usd), 0.08)
        self.assertEqual(first.debit_cost_source, "ESTIMATED")
        self.assertEqual(second.ledger_name, first.ledger_name)
        self.assertEqual(float(provider_job.debit_cost_usd), 0.08)
        self.assertEqual(provider_job.debit_cost_source, "ESTIMATED")
        self.assertEqual(history["provider_jobs"][0]["debit_cost_source"], "ESTIMATED")

    def test_failed_provider_job_creates_no_debit(self):
        project = create_project()
        workflow_run, node_run = create_started_run(project)
        model = create_model("billing_failed_provider", "0.08")
        provider_job = insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run,
                "provider": "billing_failed_provider",
                "model": model.name,
                "status": "FAILED",
                "idempotency_key": unique("billing-failed-job"),
                "estimated_cost_usd": 0.08,
                "request_json": json.dumps({"prompt": "Failed"}),
                "raw_error_json": json.dumps({"message": "provider failed"}),
            }
        )
        failed_result = NormalizedProviderResult(status="FAILED", cost_usd=0.08)

        with self.assertRaises(ProviderInvariantError):
            ProviderOutputService().materialize(
                project_name=project.name,
                workflow_run_name=workflow_run,
                node_run_name=node_run,
                provider_job_name=provider_job.name,
                result=failed_result,
                description="Failed provider debit",
            )
        self.assertFalse(
            frappe.db.exists(
                "AI Credit Ledger",
                {"provider_job": provider_job.name, "ledger_type": "DEBIT"},
            )
        )
        self.assertFalse(frappe.db.exists("AI Asset", {"source_provider_job": provider_job.name}))

    def test_zero_cost_provider_output_creates_asset_without_debit(self):
        project = create_project()
        workflow_run, node_run = create_started_run(project)
        model = create_model("billing_zero_provider", "0.00")
        provider_job = insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run,
                "provider": "billing_zero_provider",
                "model": model.name,
                "status": "SUCCEEDED",
                "idempotency_key": unique("billing-zero-job"),
                "estimated_cost_usd": 0.0,
                "request_json": json.dumps({"prompt": "Free result"}),
                "response_json": json.dumps({"status": "completed"}),
            }
        )
        result = NormalizedProviderResult(
            status="SUCCEEDED",
            external_job_id="billing-zero-1",
            outputs=(
                NormalizedProviderOutput(
                    asset_type="IMAGE",
                    url="https://example.invalid/free.png",
                    mime_type="image/png",
                    metadata={},
                ),
            ),
            cost_usd=0.0,
        )

        materialized = ProviderOutputService().materialize(
            project_name=project.name,
            workflow_run_name=workflow_run,
            node_run_name=node_run,
            provider_job_name=provider_job.name,
            result=result,
            description="Zero cost provider result",
        )

        self.assertIsNone(materialized.ledger_name)
        provider_job.reload()
        self.assertEqual(float(provider_job.debit_cost_usd), 0.0)
        self.assertEqual(provider_job.debit_cost_source, "ZERO_COST")
        self.assertTrue(frappe.db.exists("AI Asset", {"source_provider_job": provider_job.name}))
        self.assertFalse(
            frappe.db.exists(
                "AI Credit Ledger",
                {"provider_job": provider_job.name, "ledger_type": "DEBIT"},
            )
        )

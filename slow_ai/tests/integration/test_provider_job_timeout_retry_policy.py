import json
from typing import Any, Mapping
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from slow_ai.application.billing import create_top_up
from slow_ai.application.run_service import RunService
from slow_ai.domain.status import ProviderJobStatus
from slow_ai.engine.executor import WorkflowExecutor
from slow_ai.infrastructure.provider_jobs import ProviderJobRepository
from slow_ai.node_registry.nodes.export_output import ExportOutputNode
from slow_ai.node_registry.nodes.provider import ProviderTextToImageNode
from slow_ai.node_registry.nodes.text_prompt import TextPromptNode
from slow_ai.node_registry.registry import NodeRegistry
from slow_ai.providers.contracts import NormalizedProviderResult, ProviderAdapter, ProviderSubmission
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
            "project_name": unique("Timeout Project"),
            "status": "Open",
        }
    )


def create_model(provider: str):
    return insert_doc(
        {
            "doctype": "AI Model",
            "model_id": unique(f"{provider}/model"),
            "model_name": "Timeout Test Model",
            "provider": provider,
            "status": "ENABLED",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "amount_usd": 0.05}),
        }
    )


def create_provider_account(provider: str):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("Timeout Provider Account"),
            "api_key_secret": "timeout-provider-secret",
            "is_default": 1,
            "status": "ACTIVE",
        }
    )


def create_provider_workflow(project, provider: str, model_name: str):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Timeout Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Timeout prompt"}},
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


class WaitingProviderAdapter(ProviderAdapter):
    provider_name = "timeout_waiting_provider"

    def __init__(self) -> None:
        self.provider_jobs = ProviderJobRepository()
        self.submitted: list[str] = []
        self.polled: list[str] = []

    def submit_job(self, submission: ProviderSubmission) -> NormalizedProviderResult:
        self.submitted.append(submission.provider_job_name)
        self.provider_jobs.mark_submitting(submission.provider_job_name)
        result = NormalizedProviderResult(
            status=ProviderJobStatus.WAITING_PROVIDER.value,
            external_job_id="timeout-external-1",
        )
        self.provider_jobs.apply_result(
            submission.provider_job_name,
            result,
            {"data": {"id": "timeout-external-1", "status": "processing"}},
        )
        return result

    def poll_job(self, provider_job_name: str) -> NormalizedProviderResult:
        self.polled.append(provider_job_name)
        result = NormalizedProviderResult(
            status=ProviderJobStatus.WAITING_PROVIDER.value,
            external_job_id="timeout-external-1",
        )
        self.provider_jobs.apply_result(
            provider_job_name,
            result,
            {
                "data": {
                    "id": "timeout-external-1",
                    "status": "processing",
                    "secret": "raw-timeout-secret",
                    "url": "https://provider.example.invalid/raw-timeout.png",
                }
            },
        )
        return result

    def cancel_job(self, provider_job_name: str) -> None:
        self.provider_jobs.mark_cancelled(provider_job_name)

    def normalize_result(self, raw_response: Mapping[str, Any]) -> NormalizedProviderResult:
        return NormalizedProviderResult(
            status=ProviderJobStatus.WAITING_PROVIDER.value,
            external_job_id="timeout-external-1",
        )

    def estimate_cost(self, model: str, input_data: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"currency": "USD", "estimated_cost_usd": 0.05, "model": model}


def node_registry(adapter: WaitingProviderAdapter) -> NodeRegistry:
    return NodeRegistry(
        [
            TextPromptNode(),
            ProviderTextToImageNode(provider_registry=ProviderRegistry([adapter])),
            ExportOutputNode(),
        ]
    )


def create_waiting_run(adapter: WaitingProviderAdapter):
    project = create_project()
    model = create_model(adapter.provider_name)
    create_provider_account(adapter.provider_name)
    create_top_up(project.name, "1.00", "Timeout policy credit")
    workflow = create_provider_workflow(project, adapter.provider_name, model.name)
    result = RunService(node_registry=node_registry(adapter)).start_run(workflow.name)
    WorkflowExecutor(node_registry=node_registry(adapter)).run(result.workflow_run)
    provider_node_run = frappe.db.get_value(
        "AI Node Run",
        {"workflow_run": result.workflow_run, "node_id": "provider_1"},
        "name",
    )
    provider_job = frappe.get_doc(
        "AI Provider Job",
        frappe.db.get_value("AI Provider Job", {"node_run": provider_node_run}, "name"),
    )
    return project, workflow, result, provider_node_run, provider_job


class TestProviderJobTimeoutRetryPolicy(FrappeTestCase):
    def test_provider_job_exceeding_max_poll_attempts_expires_safely(self):
        adapter = WaitingProviderAdapter()
        _, _, result, node_run_name, provider_job = create_waiting_run(adapter)
        frappe.db.set_value("AI Provider Job", provider_job.name, {"max_poll_attempts": 1, "poll_attempts": 0})

        polled = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        provider_job.reload()
        node_run = frappe.get_doc("AI Node Run", node_run_name)
        workflow_run = frappe.get_doc("AI Workflow Run", result.workflow_run)
        self.assertEqual(polled["status"], "EXPIRED")
        self.assertEqual(provider_job.status, "EXPIRED")
        self.assertEqual(provider_job.poll_attempts, 1)
        self.assertTrue(provider_job.last_polled_at)
        self.assertEqual(node_run.status, "FAILED")
        self.assertIn("ProviderJobMaxPollAttemptsExceeded", node_run.error_json)
        self.assertEqual(workflow_run.status, "EXPIRED")
        self.assertIn("ProviderJobMaxPollAttemptsExceeded", workflow_run.error_json)
        self.assertEqual(adapter.polled, [provider_job.name])

    def test_provider_job_exceeding_timeout_expires_before_provider_poll(self):
        adapter = WaitingProviderAdapter()
        _, _, result, node_run_name, provider_job = create_waiting_run(adapter)
        old_submitted_at = add_to_date(now_datetime(), seconds=-120)
        frappe.db.set_value(
            "AI Provider Job",
            provider_job.name,
            {"submitted_at": old_submitted_at, "timeout_seconds": 1, "poll_attempts": 0},
        )

        polled = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        provider_job.reload()
        node_run = frappe.get_doc("AI Node Run", node_run_name)
        workflow_run = frappe.get_doc("AI Workflow Run", result.workflow_run)
        self.assertEqual(polled["status"], "EXPIRED")
        self.assertEqual(provider_job.status, "EXPIRED")
        self.assertEqual(provider_job.poll_attempts, 0)
        self.assertFalse(provider_job.last_polled_at)
        self.assertEqual(node_run.status, "FAILED")
        self.assertIn("ProviderJobTimeout", node_run.error_json)
        self.assertEqual(workflow_run.status, "EXPIRED")
        self.assertIn("ProviderJobTimeout", workflow_run.error_json)
        self.assertEqual(adapter.polled, [])

    def test_repeated_poll_after_timeout_has_no_side_effects_or_resume_loop(self):
        adapter = WaitingProviderAdapter()
        _, _, result, _, provider_job = create_waiting_run(adapter)
        frappe.db.set_value("AI Provider Job", provider_job.name, {"max_poll_attempts": 1, "poll_attempts": 0})

        first = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        second = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        self.assertEqual(first["status"], "EXPIRED")
        self.assertEqual(first["queue_job_id"], None)
        self.assertEqual(second["status"], "EXPIRED")
        self.assertEqual(second["queue_job_id"], None)
        self.assertEqual(adapter.polled, [provider_job.name])
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job.name}), 0)
        self.assertEqual(
            frappe.db.count("AI Credit Ledger", {"provider_job": provider_job.name, "ledger_type": "DEBIT"}),
            0,
        )
        self.assertEqual(frappe.db.count("AI Provider Job", {"node_run": provider_job.node_run}), 1)
        self.assertEqual(frappe.db.count("AI Workflow Run", {"name": result.workflow_run}), 1)
        self.assertEqual(frappe.db.count("AI Node Run", {"workflow_run": result.workflow_run}), 3)

    def test_cancelled_workflow_run_wins_over_timeout_policy(self):
        adapter = WaitingProviderAdapter()
        _, _, result, node_run_name, provider_job = create_waiting_run(adapter)
        frappe.db.set_value("AI Workflow Run", result.workflow_run, "status", "CANCELLED")
        frappe.db.set_value("AI Provider Job", provider_job.name, {"max_poll_attempts": 0, "timeout_seconds": 0})

        polled = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        self.assertEqual(polled["status"], "CANCELLED")
        self.assertEqual(frappe.get_doc("AI Workflow Run", result.workflow_run).status, "CANCELLED")
        self.assertEqual(frappe.get_doc("AI Node Run", node_run_name).status, "CANCELLED")
        self.assertEqual(frappe.get_doc("AI Provider Job", provider_job.name).status, "CANCELLED")
        self.assertEqual(adapter.polled, [])

    def test_public_run_detail_shows_safe_timeout_message_only(self):
        adapter = WaitingProviderAdapter()
        _, _, result, _, provider_job = create_waiting_run(adapter)
        secret = unique("timeout-secret")
        frappe.db.set_value(
            "AI Provider Job",
            provider_job.name,
            {
                "response_json": json.dumps(
                    {
                        "Authorization": f"Bearer {secret}",
                        "raw_url": "https://provider.example.invalid/raw-timeout.png",
                    }
                ),
                "raw_error_json": json.dumps({"message": f"token={secret}"}),
                "timeout_seconds": 0,
            },
        )

        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        payload = frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=result.workflow_run)
        encoded = json.dumps(payload, default=str)

        self.assertIn("Provider job timed out before completion.", encoded)
        self.assertNotIn(secret, encoded)
        self.assertNotIn("request_json", encoded)
        self.assertNotIn("response_json", encoded)
        self.assertNotIn("raw_error_json", encoded)
        self.assertNotIn("provider_account", encoded)
        self.assertNotIn("https://provider.example.invalid/raw-timeout.png", encoded)

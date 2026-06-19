import json
from typing import Any, Mapping
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.billing import create_top_up
from slow_ai.application.run_service import RunService
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
from slow_ai.workers.resume_workflow import resume_workflow
from slow_ai.workers.run_node import run_node
from slow_ai.workers.run_workflow import run_workflow


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Idempotency Project"),
            "status": "Open",
        }
    )


def create_text_workflow(project):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Idempotency Text Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Idempotent prompt"}},
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
            "layout_json": json.dumps({"nodes": []}),
        }
    )


def create_provider_model(provider: str):
    return insert_doc(
        {
            "doctype": "AI Model",
            "model_id": unique(f"{provider}/model"),
            "model_name": "Idempotency Provider Model",
            "provider": provider,
            "status": "ENABLED",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "amount_usd": 0.12}),
        }
    )


def create_provider_account(provider: str):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("Idempotency Provider Account"),
            "api_key_secret": "idempotency-secret",
            "is_default": 1,
            "status": "ACTIVE",
        }
    )


def create_provider_workflow(project, model_name: str):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Idempotency Provider Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Provider prompt"}},
                    {
                        "id": "provider_1",
                        "type": "provider_text_to_image",
                        "config": {"provider": IdempotencyProviderAdapter.provider_name, "model": model_name},
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


class IdempotencyProviderAdapter(ProviderAdapter):
    provider_name = "idempotency_provider"

    def __init__(self) -> None:
        self.provider_jobs = ProviderJobRepository()
        self.submitted: list[str] = []
        self.polled: list[str] = []

    def submit_job(self, submission: ProviderSubmission) -> NormalizedProviderResult:
        self.submitted.append(submission.provider_job_name)
        self.provider_jobs.mark_submitting(submission.provider_job_name)
        result = NormalizedProviderResult(
            status=ProviderJobStatus.WAITING_PROVIDER.value,
            external_job_id="idempotent-external-1",
        )
        self.provider_jobs.apply_result(
            submission.provider_job_name,
            result,
            {"data": {"id": "idempotent-external-1", "status": "processing"}},
        )
        return result

    def poll_job(self, provider_job_name: str) -> NormalizedProviderResult:
        self.polled.append(provider_job_name)
        result = self._success_result()
        self.provider_jobs.apply_result(
            provider_job_name,
            result,
            {
                "data": {
                    "id": "idempotent-external-1",
                    "status": "completed",
                    "outputs": ["https://example.invalid/one.png", "https://example.invalid/two.png"],
                }
            },
        )
        return result

    def cancel_job(self, provider_job_name: str) -> None:
        self.provider_jobs.mark_cancelled(provider_job_name)

    def normalize_result(self, raw_response: Mapping[str, Any]) -> NormalizedProviderResult:
        status = ((raw_response.get("data") or {}).get("status") or "").lower()
        if status == "completed":
            return self._success_result()
        return NormalizedProviderResult(
            status=ProviderJobStatus.WAITING_PROVIDER.value,
            external_job_id="idempotent-external-1",
        )

    def estimate_cost(self, model: str, input_data: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"currency": "USD", "estimated_cost_usd": 0.12, "model": model}

    def _success_result(self) -> NormalizedProviderResult:
        return NormalizedProviderResult(
            status=ProviderJobStatus.SUCCEEDED.value,
            external_job_id="idempotent-external-1",
            outputs=(
                NormalizedProviderOutput(
                    asset_type="IMAGE",
                    url="https://example.invalid/one.png",
                    mime_type="image/png",
                    metadata={"label": "one"},
                ),
                NormalizedProviderOutput(
                    asset_type="IMAGE",
                    url="https://example.invalid/two.png",
                    mime_type="image/png",
                    metadata={"label": "two"},
                ),
            ),
            cost_usd=0.12,
        )


def registry(adapter: IdempotencyProviderAdapter) -> NodeRegistry:
    return NodeRegistry(
        [
            TextPromptNode(),
            ProviderTextToImageNode(provider_registry=ProviderRegistry([adapter])),
            ExportOutputNode(),
        ]
    )


class TestRunIdempotencyRecovery(FrappeTestCase):
    def test_duplicate_start_run_reuses_recent_active_run(self):
        workflow = create_text_workflow(create_project())

        first = RunService().start_run(workflow.name)
        second = RunService().start_run(workflow.name)

        self.assertEqual(second.workflow_version, first.workflow_version)
        self.assertEqual(second.workflow_run, first.workflow_run)
        self.assertEqual(second.node_runs, first.node_runs)
        self.assertEqual(frappe.db.count("AI Workflow Version", {"workflow": workflow.name}), 1)
        self.assertEqual(frappe.db.count("AI Workflow Run", {"workflow": workflow.name}), 1)
        self.assertEqual(frappe.db.count("AI Node Run", {"workflow_run": first.workflow_run}), 2)

        frappe.delete_doc("AI Node Run", second.node_runs[-1], ignore_permissions=True, force=True)
        recovered = RunService().start_run(workflow.name)

        self.assertEqual(recovered.workflow_version, first.workflow_version)
        self.assertEqual(recovered.workflow_run, first.workflow_run)
        self.assertEqual(len(recovered.node_runs), 2)
        self.assertEqual(frappe.db.count("AI Workflow Version", {"workflow": workflow.name}), 1)
        self.assertEqual(frappe.db.count("AI Workflow Run", {"workflow": workflow.name}), 1)
        self.assertEqual(frappe.db.count("AI Node Run", {"workflow_run": first.workflow_run}), 2)

    def test_text_worker_and_node_worker_retries_do_not_duplicate_side_effects(self):
        workflow = create_text_workflow(create_project())
        result = RunService().start_run(workflow.name)
        prompt_node_run = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": result.workflow_run, "node_id": "prompt_1"},
            "name",
        )

        run_node(prompt_node_run)
        run_node(prompt_node_run)
        resume_workflow(result.workflow_run)
        run_workflow(result.workflow_run)

        self.assertEqual(frappe.db.count("AI Workflow Version", {"workflow": workflow.name}), 1)
        self.assertEqual(frappe.db.count("AI Workflow Run", {"workflow": workflow.name}), 1)
        self.assertEqual(frappe.db.count("AI Node Run", {"workflow_run": result.workflow_run}), 2)
        self.assertEqual(
            frappe.db.count("AI Provider Job", {"node_run": ["in", list(result.node_runs)]}),
            0,
        )
        self.assertEqual(frappe.get_doc("AI Workflow Run", result.workflow_run).status, "SUCCEEDED")

    def test_provider_worker_retry_does_not_duplicate_provider_job(self):
        adapter = IdempotencyProviderAdapter()
        project = create_project()
        model = create_provider_model(adapter.provider_name)
        create_provider_account(adapter.provider_name)
        create_top_up(project.name, "1.00", "Idempotency provider credit")
        workflow = create_provider_workflow(project, model.name)
        result = RunService(node_registry=registry(adapter)).start_run(workflow.name)
        executor = WorkflowExecutor(node_registry=registry(adapter))

        executor.run(result.workflow_run)
        executor.run(result.workflow_run)

        provider_jobs = frappe.get_all(
            "AI Provider Job",
            filters={"node_run": ["in", list(result.node_runs)]},
            pluck="name",
        )
        self.assertEqual(len(provider_jobs), 1)
        self.assertEqual(adapter.submitted, [provider_jobs[0]])
        self.assertEqual(
            frappe.db.count(
                "AI Provider Job",
                {"node_run": ["in", list(result.node_runs)], "idempotency_key": ["like", "%:provider_text_to_image"]},
            ),
            1,
        )

    def test_repeated_provider_poll_does_not_duplicate_assets_or_debit(self):
        adapter = IdempotencyProviderAdapter()
        project = create_project()
        model = create_provider_model(adapter.provider_name)
        create_provider_account(adapter.provider_name)
        create_top_up(project.name, "1.00", "Idempotency poll credit")
        workflow = create_provider_workflow(project, model.name)
        result = RunService(node_registry=registry(adapter)).start_run(workflow.name)
        WorkflowExecutor(node_registry=registry(adapter)).run(result.workflow_run)
        provider_job_name = frappe.db.get_value(
            "AI Provider Job",
            {"node_run": ["in", list(result.node_runs)]},
            "name",
        )

        first = poll_provider_job(provider_job_name, provider_registry=ProviderRegistry([adapter]))
        second = poll_provider_job(provider_job_name, provider_registry=ProviderRegistry([adapter]))

        self.assertEqual(first["status"], "SUCCEEDED")
        self.assertEqual(second["status"], "SUCCEEDED")
        self.assertEqual(adapter.polled, [provider_job_name])
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job_name}), 2)
        self.assertEqual(
            frappe.db.count("AI Credit Ledger", {"provider_job": provider_job_name, "ledger_type": "DEBIT"}),
            1,
        )

        resume_workflow(result.workflow_run)
        resume_workflow(result.workflow_run)
        self.assertEqual(frappe.get_doc("AI Workflow Run", result.workflow_run).status, "SUCCEEDED")
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job_name}), 2)
        self.assertEqual(
            frappe.db.count("AI Credit Ledger", {"provider_job": provider_job_name, "ledger_type": "DEBIT"}),
            1,
        )

    def test_terminal_runs_remain_terminal_when_worker_retried(self):
        for terminal_status in ("FAILED", "CANCELLED"):
            workflow = create_text_workflow(create_project())
            result = RunService().start_run(workflow.name)
            frappe.db.set_value("AI Workflow Run", result.workflow_run, "status", terminal_status)

            run_workflow(result.workflow_run)
            resume_workflow(result.workflow_run)

            self.assertEqual(frappe.get_doc("AI Workflow Run", result.workflow_run).status, terminal_status)
            self.assertEqual(frappe.db.count("AI Workflow Version", {"workflow": workflow.name}), 1)
            self.assertEqual(frappe.db.count("AI Workflow Run", {"workflow": workflow.name}), 1)
            self.assertEqual(frappe.db.count("AI Node Run", {"workflow_run": result.workflow_run}), 2)

    def test_provider_poller_does_not_progress_terminal_workflow_run(self):
        adapter = IdempotencyProviderAdapter()
        project = create_project()
        model = create_provider_model(adapter.provider_name)
        create_provider_account(adapter.provider_name)
        create_top_up(project.name, "1.00", "Idempotency terminal poll credit")
        workflow = create_provider_workflow(project, model.name)
        result = RunService(node_registry=registry(adapter)).start_run(workflow.name)
        WorkflowExecutor(node_registry=registry(adapter)).run(result.workflow_run)
        provider_job_name = frappe.db.get_value(
            "AI Provider Job",
            {"node_run": ["in", list(result.node_runs)]},
            "name",
        )
        provider_node_run = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": result.workflow_run, "node_id": "provider_1"},
            "name",
        )
        frappe.db.set_value("AI Workflow Run", result.workflow_run, "status", "FAILED")

        polled = poll_provider_job(provider_job_name, provider_registry=ProviderRegistry([adapter]))

        self.assertEqual(polled["queue_job_id"], None)
        self.assertEqual(adapter.polled, [])
        self.assertEqual(frappe.get_doc("AI Workflow Run", result.workflow_run).status, "FAILED")
        self.assertEqual(frappe.get_doc("AI Node Run", provider_node_run).status, "WAITING_PROVIDER")
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job_name}), 0)
        self.assertEqual(
            frappe.db.count("AI Credit Ledger", {"provider_job": provider_job_name, "ledger_type": "DEBIT"}),
            0,
        )

    def test_public_run_detail_remains_safe_after_provider_payloads(self):
        adapter = IdempotencyProviderAdapter()
        project = create_project()
        model = create_provider_model(adapter.provider_name)
        create_provider_account(adapter.provider_name)
        create_top_up(project.name, "1.00", "Idempotency public safety credit")
        workflow = create_provider_workflow(project, model.name)
        result = RunService(node_registry=registry(adapter)).start_run(workflow.name)
        WorkflowExecutor(node_registry=registry(adapter)).run(result.workflow_run)
        provider_job_name = frappe.db.get_value(
            "AI Provider Job",
            {"node_run": ["in", list(result.node_runs)]},
            "name",
        )
        secret = unique("provider-secret")
        frappe.db.set_value(
            "AI Provider Job",
            provider_job_name,
            {
                "request_json": json.dumps({"Authorization": f"Bearer {secret}"}),
                "response_json": json.dumps({"raw_provider_url": "https://provider.example.invalid/out.png"}),
                "raw_error_json": json.dumps({"message": f"token={secret}"}),
            },
        )

        payload = frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=result.workflow_run)
        encoded = json.dumps(payload, default=str)

        self.assertNotIn("request_json", encoded)
        self.assertNotIn("response_json", encoded)
        self.assertNotIn("raw_error_json", encoded)
        self.assertNotIn(secret, encoded)
        self.assertNotIn("provider_account", encoded)

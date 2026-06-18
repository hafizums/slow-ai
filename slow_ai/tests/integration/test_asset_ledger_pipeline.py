import json
from typing import Any, Mapping
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

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


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


class AsyncProviderAdapter(ProviderAdapter):
    provider_name = "async_provider"

    def __init__(self) -> None:
        self.provider_jobs = ProviderJobRepository()

    def submit_job(self, submission: ProviderSubmission) -> NormalizedProviderResult:
        self.provider_jobs.mark_submitting(submission.provider_job_name)
        result = NormalizedProviderResult(
            status=ProviderJobStatus.WAITING_PROVIDER.value,
            external_job_id="async-external-123",
        )
        self.provider_jobs.apply_result(
            submission.provider_job_name,
            result,
            {"code": 200, "data": {"id": "async-external-123", "status": "processing"}},
        )
        return result

    def poll_job(self, provider_job_name: str) -> NormalizedProviderResult:
        result = NormalizedProviderResult(
            status=ProviderJobStatus.SUCCEEDED.value,
            external_job_id="async-external-123",
            outputs=(
                NormalizedProviderOutput(
                    asset_type="IMAGE",
                    url="https://example.invalid/async-output.png",
                    mime_type="image/png",
                    metadata={"source": "async-provider"},
                ),
            ),
            cost_usd=0.11,
        )
        self.provider_jobs.apply_result(
            provider_job_name,
            result,
            {"code": 200, "data": {"id": "async-external-123", "status": "completed"}},
        )
        return result

    def cancel_job(self, provider_job_name: str) -> None:
        self.provider_jobs.mark_cancelled(provider_job_name)

    def normalize_result(self, raw_response: Mapping[str, Any]) -> NormalizedProviderResult:
        return NormalizedProviderResult(status=ProviderJobStatus.SUCCEEDED.value)

    def estimate_cost(self, model: str, input_data: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"currency": "USD", "estimated_cost_usd": 0.11, "model": model}


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Pipeline Project"),
            "status": "Open",
        }
    )


def create_model():
    return insert_doc(
        {
            "doctype": "AI Model",
            "model_id": unique("async-provider/model"),
            "model_name": "Async Provider Model",
            "provider": "async_provider",
            "status": "ENABLED",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "amount_usd": 0.11}),
        }
    )


def create_provider_account():
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": "async_provider",
            "account_label": unique("Async Provider Account"),
            "api_key_secret": "async-provider-test-key",
            "is_default": 1,
            "status": "ACTIVE",
        }
    )


def create_workflow(project, model_name: str):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Pipeline Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Async prompt"}},
                    {
                        "id": "provider_1",
                        "type": "provider_text_to_image",
                        "config": {"provider": "async_provider", "model": model_name},
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


def registry(adapter: AsyncProviderAdapter) -> NodeRegistry:
    provider_registry = ProviderRegistry([adapter])
    return NodeRegistry(
        [
            TextPromptNode(),
            ProviderTextToImageNode(provider_registry=provider_registry),
            ExportOutputNode(),
        ]
    )


class TestAssetLedgerPipeline(FrappeTestCase):
    def test_async_provider_poll_materializes_assets_and_ledger_idempotently(self):
        adapter = AsyncProviderAdapter()
        node_registry = registry(adapter)
        project = create_project()
        model = create_model()
        create_provider_account()
        workflow = create_workflow(project, model.name)
        start_result = RunService(node_registry=node_registry).start_run(workflow.name)

        WorkflowExecutor(node_registry=node_registry).run(start_result.workflow_run)

        provider_node_run = frappe.get_doc(
            "AI Node Run",
            frappe.db.get_value(
                "AI Node Run",
                {"workflow_run": start_result.workflow_run, "node_id": "provider_1"},
                "name",
            ),
        )
        self.assertEqual(provider_node_run.status, "WAITING_PROVIDER")
        self.assertEqual(
            frappe.get_doc("AI Workflow Run", start_result.workflow_run).status,
            "WAITING_PROVIDER",
        )

        provider_job = frappe.get_doc("AI Provider Job", provider_node_run.provider_job)
        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))
        poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        provider_node_run.reload()
        asset_names = frappe.get_all(
            "AI Asset",
            filters={"source_provider_job": provider_job.name},
            pluck="name",
        )
        ledger_names = frappe.get_all(
            "AI Credit Ledger",
            filters={"provider_job": provider_job.name, "ledger_type": "DEBIT"},
            pluck="name",
        )

        self.assertEqual(provider_node_run.status, "SUCCEEDED")
        self.assertEqual(len(asset_names), 1)
        self.assertEqual(len(ledger_names), 1)
        self.assertEqual(json.loads(provider_node_run.output_json)["image"], asset_names[0])
        self.assertEqual(float(frappe.get_doc("AI Credit Ledger", ledger_names[0]).amount_usd), 0.11)

        resume_workflow(start_result.workflow_run)

        output_node_run = frappe.get_doc(
            "AI Node Run",
            frappe.db.get_value(
                "AI Node Run",
                {"workflow_run": start_result.workflow_run, "node_id": "output_1"},
                "name",
            ),
        )
        self.assertEqual(frappe.get_doc("AI Workflow Run", start_result.workflow_run).status, "SUCCEEDED")
        self.assertEqual(output_node_run.status, "SUCCEEDED")
        self.assertEqual(json.loads(output_node_run.input_json)["image"], asset_names[0])

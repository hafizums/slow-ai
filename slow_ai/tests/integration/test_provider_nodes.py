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
from slow_ai.node_registry.nodes.provider import (
    ProviderImageToImageNode,
    ProviderImageToVideoNode,
    ProviderStartEndToVideoNode,
    ProviderTextToImageNode,
    ProviderTextToSpeechNode,
)
from slow_ai.node_registry.nodes.text_prompt import TextPromptNode
from slow_ai.node_registry.registry import NodeRegistry
from slow_ai.providers.contracts import (
    NormalizedProviderOutput,
    NormalizedProviderResult,
    ProviderAdapter,
    ProviderSubmission,
)
from slow_ai.providers.registry import ProviderRegistry


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


class DeterministicProviderAdapter(ProviderAdapter):
    provider_name = "test_provider"

    def __init__(
        self,
        *,
        asset_type: str = "IMAGE",
        url: str = "https://example.invalid/generated.png",
        mime_type: str = "image/png",
        cost_usd: float = 0.17,
    ) -> None:
        self.provider_jobs = ProviderJobRepository()
        self.asset_type = asset_type
        self.url = url
        self.mime_type = mime_type
        self.cost_usd = cost_usd
        self.provider_job_existed_before_submit = False
        self.submissions: list[Mapping[str, Any]] = []

    def submit_job(self, submission: ProviderSubmission) -> NormalizedProviderResult:
        provider_job = self.provider_jobs.get(submission.provider_job_name)
        self.provider_job_existed_before_submit = provider_job.status == ProviderJobStatus.QUEUED.value
        self.submissions.append({"model": submission.model, "input_data": dict(submission.input_data)})
        self.provider_jobs.mark_submitting(submission.provider_job_name)
        result = NormalizedProviderResult(
            status=ProviderJobStatus.SUCCEEDED.value,
            external_job_id="external-provider-job-123",
            outputs=(
                NormalizedProviderOutput(
                    asset_type=self.asset_type,
                    url=self.url,
                    mime_type=self.mime_type,
                    metadata={"provider": self.provider_name},
                ),
            ),
            cost_usd=self.cost_usd,
        )
        self.provider_jobs.apply_result(
            submission.provider_job_name,
            result,
            {"code": 200, "data": {"id": result.external_job_id, "status": "completed"}},
        )
        return result

    def poll_job(self, provider_job_name: str) -> NormalizedProviderResult:
        return NormalizedProviderResult(status=ProviderJobStatus.SUCCEEDED.value)

    def cancel_job(self, provider_job_name: str) -> None:
        self.provider_jobs.mark_cancelled(provider_job_name)

    def normalize_result(self, raw_response: Mapping[str, Any]) -> NormalizedProviderResult:
        return NormalizedProviderResult(status=ProviderJobStatus.SUCCEEDED.value)

    def estimate_cost(self, model: str, input_data: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"currency": "USD", "estimated_cost_usd": self.cost_usd, "model": model}


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Provider Node Project"),
            "status": "Open",
        }
    )


def create_model(provider: str = "test_provider"):
    return insert_doc(
        {
            "doctype": "AI Model",
            "model_id": unique(f"{provider}/model"),
            "model_name": "Provider Node Test Model",
            "provider": provider,
            "status": "ENABLED",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "amount_usd": 0.17}),
        }
    )


def create_provider_account(provider: str = "test_provider"):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("Provider Node Account"),
            "api_key_secret": "provider-node-test-key",
            "is_default": 1,
            "status": "ACTIVE",
        }
    )


def create_workflow(project, model_name: str):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Provider Node Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {
                        "id": "prompt_1",
                        "type": "text_prompt",
                        "config": {"text": "A cinematic product shot"},
                    },
                    {
                        "id": "provider_1",
                        "type": "provider_text_to_image",
                        "config": {
                            "provider": "test_provider",
                            "model": model_name,
                            "parameters": {"aspect_ratio": "1:1"},
                        },
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


def provider_node_registry(adapter: DeterministicProviderAdapter) -> NodeRegistry:
    provider_registry = ProviderRegistry([adapter])
    return NodeRegistry(
        [
            TextPromptNode(),
            ProviderTextToImageNode(provider_registry=provider_registry),
            ProviderImageToImageNode(provider_registry=provider_registry),
            ProviderImageToVideoNode(provider_registry=provider_registry),
            ProviderStartEndToVideoNode(provider_registry=provider_registry),
            ProviderTextToSpeechNode(provider_registry=provider_registry),
            ExportOutputNode(),
        ]
    )


class TestProviderNodes(FrappeTestCase):
    def test_provider_text_to_image_node_persists_provider_job_asset_and_ledger(self):
        project = create_project()
        model = create_model()
        create_provider_account()
        create_top_up(project.name, "0.50", "Provider node test credit")
        adapter = DeterministicProviderAdapter()
        registry = provider_node_registry(adapter)
        workflow = create_workflow(project, model.name)

        start_result = RunService(node_registry=registry).start_run(workflow.name)
        WorkflowExecutor(node_registry=registry).run(start_result.workflow_run)

        provider_node_run = frappe.get_doc(
            "AI Node Run",
            frappe.db.get_value(
                "AI Node Run",
                {"workflow_run": start_result.workflow_run, "node_id": "provider_1"},
                "name",
            ),
        )
        provider_job = frappe.get_doc("AI Provider Job", provider_node_run.provider_job)
        asset = frappe.get_doc(
            "AI Asset",
            frappe.db.get_value("AI Asset", {"source_provider_job": provider_job.name}, "name"),
        )
        ledger = frappe.get_doc(
            "AI Credit Ledger",
            frappe.db.get_value("AI Credit Ledger", {"provider_job": provider_job.name}, "name"),
        )
        output_node = frappe.get_doc(
            "AI Node Run",
            frappe.db.get_value(
                "AI Node Run",
                {"workflow_run": start_result.workflow_run, "node_id": "output_1"},
                "name",
            ),
        )

        self.assertTrue(adapter.provider_job_existed_before_submit)
        self.assertEqual(provider_job.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertEqual(provider_job.provider, "test_provider")
        self.assertEqual(json.loads(provider_job.request_json)["prompt"], "A cinematic product shot")
        self.assertEqual(json.loads(provider_job.request_json)["aspect_ratio"], "1:1")
        self.assertEqual(provider_node_run.status, "SUCCEEDED")
        self.assertEqual(provider_node_run.provider_job, provider_job.name)
        self.assertEqual(float(provider_node_run.cost_usd), 0.17)
        self.assertEqual(asset.asset_type, "IMAGE")
        self.assertEqual(asset.url, "https://example.invalid/generated.png")
        self.assertEqual(asset.source_node_run, provider_node_run.name)
        self.assertEqual(float(ledger.amount_usd), 0.17)
        self.assertEqual(ledger.reference_name, provider_job.name)
        self.assertEqual(json.loads(output_node.input_json)["image"], asset.name)

    def test_provider_text_to_speech_node_accepts_configured_text_input(self):
        project = create_project()
        model = create_model()
        create_provider_account()
        create_top_up(project.name, "0.50", "Provider TTS test credit")
        adapter = DeterministicProviderAdapter(
            asset_type="AUDIO",
            url="https://example.invalid/generated.mp3",
            mime_type="audio/mpeg",
            cost_usd=0.05,
        )
        provider_registry = ProviderRegistry([adapter])
        registry = NodeRegistry(
            [
                ProviderTextToSpeechNode(provider_registry=provider_registry),
                ExportOutputNode(),
            ]
        )
        workflow = insert_doc(
            {
                "doctype": "AI Workflow",
                "title": unique("Provider TTS Workflow"),
                "project": project.name,
                "status": "DRAFT",
                "draft_nodes_json": json.dumps(
                    [
                        {
                            "id": "tts_1",
                            "type": "provider_text_to_speech",
                            "config": {
                                "provider": "test_provider",
                                "model": model.name,
                                "text": "Narration text",
                            },
                        },
                        {"id": "output_1", "type": "export_output", "config": {}},
                    ]
                ),
                "draft_edges_json": json.dumps(
                    [
                        {
                            "id": "edge_1",
                            "source": "tts_1",
                            "source_port": "audio",
                            "target": "output_1",
                            "target_port": "audio",
                        }
                    ]
                ),
                "layout_json": json.dumps({"nodes": []}),
            }
        )

        start_result = RunService(node_registry=registry).start_run(workflow.name)
        WorkflowExecutor(node_registry=registry).run(start_result.workflow_run)

        provider_job_name = frappe.db.get_value(
            "AI Provider Job",
            {"provider": "test_provider", "model": model.name},
            "name",
        )
        provider_job = frappe.get_doc("AI Provider Job", provider_job_name)
        asset = frappe.get_doc(
            "AI Asset",
            frappe.db.get_value("AI Asset", {"source_provider_job": provider_job.name}, "name"),
        )

        self.assertEqual(json.loads(provider_job.request_json)["text"], "Narration text")
        self.assertEqual(asset.asset_type, "AUDIO")
        self.assertEqual(asset.mime_type, "audio/mpeg")

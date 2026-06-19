import json
from typing import Any, Mapping
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.billing import create_top_up
from slow_ai.application.run_service import RunService
from slow_ai.domain.exceptions import RunPreflightError
from slow_ai.domain.status import ProviderJobStatus
from slow_ai.engine.executor import WorkflowExecutor
from slow_ai.node_registry.nodes.export_output import ExportOutputNode
from slow_ai.node_registry.nodes.provider import ProviderTextToImageNode
from slow_ai.node_registry.nodes.text_prompt import TextPromptNode
from slow_ai.node_registry.registry import NodeRegistry
from slow_ai.providers.contracts import ProviderJobRequest
from slow_ai.providers.registry import ProviderRegistry, create_default_provider_registry
from slow_ai.providers.replicate.adapter import ReplicateAdapter
from slow_ai.providers.replicate.auth import ReplicateAuth
from slow_ai.providers.replicate.models import REPLICATE_PROVIDER_NAME, upsert_replicate_model_catalog
from slow_ai.providers.replicate.normalizer import ReplicateNormalizer


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


class RecordingReplicateClient:
    def __init__(
        self,
        *,
        idempotency_key: str,
        submit_status: str = "starting",
        include_cost: bool = True,
    ) -> None:
        self.idempotency_key = idempotency_key
        self.submit_status = submit_status
        self.include_cost = include_cost
        self.created: list[Mapping[str, Any]] = []
        self.polled: list[str] = []
        self.cancelled: list[str] = []

    def create_prediction(
        self,
        api_key: str,
        version: str,
        input_data: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        existing = frappe.get_all(
            "AI Provider Job",
            filters={
                "idempotency_key": self.idempotency_key,
                "status": ProviderJobStatus.SUBMITTING.value,
            },
            fields=["name"],
            limit=1,
        )
        assert existing, "AI Provider Job must exist before external Replicate submission."
        self.created.append({"api_key": api_key, "version": version, "input": dict(input_data)})
        raw_response: dict[str, Any] = {
            "id": "replicate-prediction-submit",
            "status": self.submit_status,
            "model": version,
            "version": version,
            "urls": {
                "get": "https://api.replicate.com/v1/predictions/replicate-prediction-submit",
                "cancel": "https://api.replicate.com/v1/predictions/replicate-prediction-submit/cancel",
            },
        }
        if self.submit_status == "succeeded":
            raw_response["output"] = ["https://replicate.delivery/pbxt/generated.webp"]
            if self.include_cost:
                raw_response["metrics"] = {"cost_usd": 0.003}
        return raw_response

    def get_prediction(self, api_key: str, prediction_id: str) -> Mapping[str, Any]:
        self.polled.append(prediction_id)
        raw_response: dict[str, Any] = {
            "id": prediction_id,
            "status": "succeeded",
            "output": ["https://replicate.delivery/pbxt/polled-generated.webp"],
            "urls": {
                "get": f"https://api.replicate.com/v1/predictions/{prediction_id}",
                "cancel": f"https://api.replicate.com/v1/predictions/{prediction_id}/cancel",
            },
        }
        if self.include_cost:
            raw_response["metrics"] = {"cost_usd": 0.003}
        return raw_response

    def cancel_prediction(self, api_key: str, prediction_id: str) -> Mapping[str, Any]:
        self.cancelled.append(prediction_id)
        return {"id": prediction_id, "status": "canceled"}


class FailedReplicateClient(RecordingReplicateClient):
    def get_prediction(self, api_key: str, prediction_id: str) -> Mapping[str, Any]:
        self.polled.append(prediction_id)
        return {"id": prediction_id, "status": "failed", "error": "Generation failed."}


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Replicate Project"),
            "status": "Open",
        }
    )


def create_model(
    provider: str = REPLICATE_PROVIDER_NAME,
    *,
    pricing: str = "0.003",
    status: str = "ENABLED",
):
    return insert_doc(
        {
            "doctype": "AI Model",
            "model_id": unique("black-forest-labs/flux-schnell"),
            "model_slug": unique("replicate-flux-schnell"),
            "model_name": "Replicate Flux Schnell Test",
            "provider": provider,
            "status": status,
            "node_type": "provider_text_to_image",
            "category": "provider",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "test_cost_usd": pricing, "currency": "USD"}),
            "capabilities_json": json.dumps({"text_to_image": True}),
            "input_metadata_json": json.dumps({"prompt": "text"}),
            "output_metadata_json": json.dumps({"image": "AI Asset"}),
        }
    )


def create_provider_account(
    provider: str = REPLICATE_PROVIDER_NAME,
    *,
    status: str = "ACTIVE",
    is_default: int = 1,
    project: str | None = None,
):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("Replicate Account"),
            "project": project,
            "api_key_secret": "replicate-test-secret",
            "is_default": is_default,
            "status": status,
        }
    )


def create_workflow(project, *, provider: str, model_ref: str, provider_account: str | None = None):
    config = {
        "provider": provider,
        "model": model_ref,
        "parameters": {
            "aspect_ratio": "1:1",
            "num_outputs": 1,
            "output_format": "webp",
            "output_quality": 80,
            "num_inference_steps": 4,
        },
    }
    if provider_account:
        config["provider_account"] = provider_account
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Replicate Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "A small product photo"}},
                    {"id": "provider_1", "type": "provider_text_to_image", "config": config},
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


def node_registry(adapter: ReplicateAdapter) -> NodeRegistry:
    provider_registry = ProviderRegistry([adapter])
    return NodeRegistry(
        [
            TextPromptNode(),
            ProviderTextToImageNode(provider_registry=provider_registry),
            ExportOutputNode(),
        ]
    )


class TestReplicateProvider(FrappeTestCase):
    def test_default_provider_registry_includes_wavespeed_and_replicate(self):
        registry = create_default_provider_registry()

        self.assertTrue(registry.has("wavespeed"))
        self.assertTrue(registry.has(REPLICATE_PROVIDER_NAME))
        self.assertIsInstance(registry.get(REPLICATE_PROVIDER_NAME), ReplicateAdapter)

    def test_replicate_catalog_seed_and_model_metadata_are_safe(self):
        provider_job_count = frappe.db.count("AI Provider Job")

        names = upsert_replicate_model_catalog()
        listed = frappe.call("slow_ai.api.models.list_models", provider=REPLICATE_PROVIDER_NAME, status="ALL")
        detail = frappe.call("slow_ai.api.models.get_model", model="replicate-flux-schnell")

        self.assertIn("black-forest-labs/flux-schnell", names)
        self.assertIn("black-forest-labs/flux-schnell", {row["name"] for row in listed["models"]})
        self.assertEqual(detail["model"]["provider"], REPLICATE_PROVIDER_NAME)
        self.assertTrue(detail["model"]["pricing_known"])
        self.assertNotIn("pricing_json", json.dumps(detail, default=str))
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)

    def test_replicate_auth_reads_server_side_byok_secret(self):
        account = create_provider_account()

        self.assertEqual(ReplicateAuth().get_api_key(account.name), "replicate-test-secret")

    def test_create_and_submit_job_persists_provider_job_before_external_submit(self):
        model = create_model()
        account = create_provider_account()
        idempotency_key = unique("replicate-submit")
        client = RecordingReplicateClient(idempotency_key=idempotency_key)
        adapter = ReplicateAdapter(client=client)

        result = adapter.create_and_submit_job(
            ProviderJobRequest(
                provider=REPLICATE_PROVIDER_NAME,
                model=model.name,
                provider_account_name=account.name,
                idempotency_key=idempotency_key,
                input_data={"prompt": "A product shot", "aspect_ratio": "1:1"},
            )
        )

        provider_job_name = frappe.get_value(
            "AI Provider Job",
            {"idempotency_key": idempotency_key},
            "name",
        )
        provider_job = frappe.get_doc("AI Provider Job", provider_job_name)
        self.assertEqual(result.status, ProviderJobStatus.SUBMITTED.value)
        self.assertEqual(provider_job.status, ProviderJobStatus.SUBMITTED.value)
        self.assertEqual(provider_job.external_job_id, "replicate-prediction-submit")
        self.assertEqual(float(provider_job.estimated_cost_usd), 0.003)
        self.assertEqual(json.loads(provider_job.request_json)["prompt"], "A product shot")
        self.assertEqual(client.created[0]["api_key"], "replicate-test-secret")
        self.assertEqual(client.created[0]["version"], model.model_id)
        self.assertTrue(provider_job.submitted_at)

    def test_poll_job_persists_completed_result_and_normalized_outputs(self):
        model = create_model()
        account = create_provider_account()
        idempotency_key = unique("replicate-poll")
        client = RecordingReplicateClient(idempotency_key=idempotency_key)
        adapter = ReplicateAdapter(client=client)
        adapter.create_and_submit_job(
            ProviderJobRequest(
                provider=REPLICATE_PROVIDER_NAME,
                model=model.name,
                provider_account_name=account.name,
                idempotency_key=idempotency_key,
                input_data={"prompt": "A product shot"},
            )
        )
        provider_job_name = frappe.get_value(
            "AI Provider Job",
            {"idempotency_key": idempotency_key},
            "name",
        )

        result = adapter.poll_job(provider_job_name)

        provider_job = frappe.get_doc("AI Provider Job", provider_job_name)
        self.assertEqual(result.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertEqual(provider_job.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertEqual(result.outputs[0].asset_type, "IMAGE")
        self.assertEqual(result.outputs[0].mime_type, "image/webp")
        self.assertEqual(result.cost_usd, 0.003)
        self.assertTrue(provider_job.completed_at)

    def test_poll_job_persists_failed_result_error_payload(self):
        model = create_model()
        account = create_provider_account()
        idempotency_key = unique("replicate-failed")
        client = FailedReplicateClient(idempotency_key=idempotency_key)
        adapter = ReplicateAdapter(client=client)
        adapter.create_and_submit_job(
            ProviderJobRequest(
                provider=REPLICATE_PROVIDER_NAME,
                model=model.name,
                provider_account_name=account.name,
                idempotency_key=idempotency_key,
                input_data={"prompt": "A product shot"},
            )
        )
        provider_job_name = frappe.get_value(
            "AI Provider Job",
            {"idempotency_key": idempotency_key},
            "name",
        )

        result = adapter.poll_job(provider_job_name)

        provider_job = frappe.get_doc("AI Provider Job", provider_job_name)
        self.assertEqual(result.status, ProviderJobStatus.FAILED.value)
        self.assertEqual(provider_job.status, ProviderJobStatus.FAILED.value)
        self.assertEqual(json.loads(provider_job.raw_error_json)["message"], "Generation failed.")

    def test_provider_node_workflow_uses_replicate_generic_pipeline(self):
        project = create_project()
        model = create_model()
        account = create_provider_account(project=project.name)
        create_top_up(project.name, "0.02", "Replicate provider node credit")
        idempotency_key = None
        client = RecordingReplicateClient(idempotency_key="", submit_status="succeeded", include_cost=False)
        adapter = ReplicateAdapter(client=client)
        workflow = create_workflow(
            project,
            provider=REPLICATE_PROVIDER_NAME,
            model_ref=model.model_slug,
            provider_account=account.name,
        )

        start_result = RunService(node_registry=node_registry(adapter)).start_run(workflow.name)
        node_run_name = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": start_result.workflow_run, "node_id": "provider_1"},
            "name",
        )
        idempotency_key = f"{node_run_name}:provider_text_to_image"
        client.idempotency_key = idempotency_key
        WorkflowExecutor(node_registry=node_registry(adapter)).run(start_result.workflow_run)

        provider_node_run = frappe.get_doc("AI Node Run", node_run_name)
        provider_job = frappe.get_doc("AI Provider Job", provider_node_run.provider_job)
        asset = frappe.get_doc(
            "AI Asset",
            frappe.db.get_value("AI Asset", {"source_provider_job": provider_job.name}, "name"),
        )
        ledger = frappe.get_doc(
            "AI Credit Ledger",
            frappe.db.get_value("AI Credit Ledger", {"provider_job": provider_job.name}, "name"),
        )

        self.assertEqual(provider_job.provider, REPLICATE_PROVIDER_NAME)
        self.assertEqual(provider_job.model, model.name)
        self.assertEqual(provider_job.provider_account, account.name)
        self.assertEqual(provider_job.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertEqual(float(provider_job.cost_usd or 0), 0.0)
        self.assertEqual(float(provider_job.estimated_cost_usd), 0.003)
        self.assertEqual(float(provider_job.debit_cost_usd), 0.003)
        self.assertEqual(provider_job.debit_cost_source, "ESTIMATED")
        self.assertEqual(asset.asset_type, "IMAGE")
        self.assertEqual(asset.mime_type, "image/webp")
        self.assertEqual(float(ledger.amount_usd), 0.003)
        self.assertIn("estimated", ledger.description.lower())
        self.assertEqual(client.created[0]["version"], model.model_id)

    def test_replicate_provider_preflight_rejects_bad_model_account_and_balance(self):
        provider = REPLICATE_PROVIDER_NAME
        other_provider = unique("other-provider")
        project = create_project()
        other_model = create_model(other_provider)
        model = create_model(provider)
        other_account = create_provider_account(other_provider, is_default=0)
        inactive_account = create_provider_account(provider, status="DISABLED", is_default=0)

        self.assert_preflight_rejects_without_provider_job(
            create_workflow(project, provider=provider, model_ref=other_model.name),
            "belongs to provider",
        )
        self.assert_preflight_rejects_without_provider_job(
            create_workflow(project, provider=provider, model_ref=model.name, provider_account=other_account.name),
            "belongs to provider",
        )
        self.assert_preflight_rejects_without_provider_job(
            create_workflow(project, provider=provider, model_ref=model.name, provider_account=inactive_account.name),
            "is not active",
        )

        no_account_provider = unique("replicate-no-account-provider")
        no_account_model = create_model(no_account_provider)
        self.assert_preflight_rejects_without_provider_job(
            create_workflow(project, provider=no_account_provider, model_ref=no_account_model.name),
            "No active default provider account",
        )

        expensive_model = create_model(provider, pricing="0.50")
        create_provider_account(provider)
        self.assert_preflight_rejects_without_provider_job(
            create_workflow(create_project(), provider=provider, model_ref=expensive_model.name),
            "exceeds available project credit balance",
        )

    def test_replicate_normalizer_maps_cancelled_and_text_outputs(self):
        normalizer = ReplicateNormalizer()

        cancelled = normalizer.normalize({"id": "pred_cancelled", "status": "canceled"})
        text = normalizer.normalize({"id": "pred_text", "status": "succeeded", "output": "hello.txt"})

        self.assertEqual(cancelled.status, ProviderJobStatus.CANCELLED.value)
        self.assertEqual(text.outputs[0].asset_type, "TEXT")
        self.assertEqual(text.outputs[0].mime_type, "text/plain")

    def assert_preflight_rejects_without_provider_job(self, workflow, message: str) -> None:
        provider_job_count = frappe.db.count("AI Provider Job")
        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertIn(message, str(exc.exception))
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)
        self.assertFalse(frappe.db.exists("AI Workflow Version", {"workflow": workflow.name}))
        self.assertFalse(frappe.db.exists("AI Workflow Run", {"workflow": workflow.name}))

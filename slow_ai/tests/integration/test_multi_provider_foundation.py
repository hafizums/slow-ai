import json
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.billing import create_top_up
from slow_ai.application.run_service import RunService
from slow_ai.domain.exceptions import RegistryError, RunPreflightError
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
from slow_ai.providers.registry import ProviderRegistry, create_default_provider_registry


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


class DeterministicProviderAdapter(ProviderAdapter):
    def __init__(self, provider_name: str, *, cost_usd: float = 0.03) -> None:
        self.provider_name = provider_name
        self.cost_usd = cost_usd
        self.provider_jobs = ProviderJobRepository()
        self.submissions: list[Mapping[str, Any]] = []

    def submit_job(self, submission: ProviderSubmission) -> NormalizedProviderResult:
        provider_job = self.provider_jobs.get(submission.provider_job_name)
        self.submissions.append(
            {
                "provider_job": provider_job.name,
                "provider_account": provider_job.provider_account,
                "model": submission.model,
                "input_data": dict(submission.input_data),
            }
        )
        self.provider_jobs.mark_submitting(submission.provider_job_name)
        result = NormalizedProviderResult(
            status=ProviderJobStatus.SUCCEEDED.value,
            external_job_id=f"{self.provider_name}-external",
            outputs=(
                NormalizedProviderOutput(
                    asset_type="IMAGE",
                    url=f"https://example.invalid/{self.provider_name}.png",
                    mime_type="image/png",
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
            "project_name": unique("Multi Provider Project"),
            "status": "Open",
        }
    )


def create_model(provider: str, *, pricing: str = "0.03", node_type: str = "provider_text_to_image"):
    return insert_doc(
        {
            "doctype": "AI Model",
            "model_id": unique(f"{provider}/model"),
            "model_slug": unique(f"{provider}-slug"),
            "model_name": "Multi Provider Test Model",
            "provider": provider,
            "status": "ENABLED",
            "node_type": node_type,
            "category": "provider",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "amount_usd": pricing}),
            "capabilities_json": json.dumps({"text_to_image": True}),
            "input_metadata_json": json.dumps({"prompt": "text"}),
            "output_metadata_json": json.dumps({"image": "AI Asset"}),
        }
    )


def create_provider_account(provider: str, *, status: str = "ACTIVE", is_default: int = 1):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("Multi Provider Account"),
            "api_key_secret": "multi-provider-test-secret",
            "is_default": is_default,
            "status": status,
        }
    )


def create_workflow(project, *, provider: str, model_ref: str, provider_account: str | None = None):
    config = {"provider": provider, "model": model_ref, "parameters": {"size": "1024*1024"}}
    if provider_account:
        config["provider_account"] = provider_account
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Multi Provider Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Generic prompt"}},
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


def node_registry(provider_registry: ProviderRegistry) -> NodeRegistry:
    return NodeRegistry(
        [
            TextPromptNode(),
            ProviderTextToImageNode(provider_registry=provider_registry),
            ExportOutputNode(),
        ]
    )


class TestMultiProviderFoundation(FrappeTestCase):
    def test_default_registry_preserves_wavespeed_and_registry_accepts_multiple_adapters(self):
        default_registry = create_default_provider_registry()
        first = DeterministicProviderAdapter(unique("provider-a"))
        second = DeterministicProviderAdapter(unique("provider-b"))
        registry = ProviderRegistry()

        registry.register_many([first, second])

        self.assertTrue(default_registry.has("wavespeed"))
        self.assertTrue(registry.has(f" {first.provider_name} "))
        self.assertEqual(registry.get(second.provider_name), second)
        self.assertEqual(set(registry.provider_names()), {first.provider_name, second.provider_name})
        with self.assertRaises(RegistryError):
            registry.register(DeterministicProviderAdapter(first.provider_name))

    def test_provider_node_uses_default_active_account_and_debits_generically(self):
        provider = unique("second-provider")
        adapter = DeterministicProviderAdapter(provider, cost_usd=0.03)
        registry = ProviderRegistry([adapter])
        project = create_project()
        model = create_model(provider, pricing="0.03")
        provider_account = create_provider_account(provider)
        create_top_up(project.name, "0.10", "Multi-provider default account credit")
        workflow = create_workflow(project, provider=provider, model_ref=model.model_slug)

        start_result = RunService(node_registry=node_registry(registry)).start_run(workflow.name)
        WorkflowExecutor(node_registry=node_registry(registry)).run(start_result.workflow_run)

        provider_job = frappe.get_doc(
            "AI Provider Job",
            frappe.db.get_value("AI Provider Job", {"provider": provider}, "name"),
        )
        ledger = frappe.get_doc(
            "AI Credit Ledger",
            frappe.db.get_value("AI Credit Ledger", {"provider_job": provider_job.name}, "name"),
        )
        self.assertEqual(provider_job.provider_account, provider_account.name)
        self.assertEqual(adapter.submissions[0]["provider_account"], provider_account.name)
        self.assertEqual(provider_job.model, model.name)
        self.assertEqual(adapter.submissions[0]["model"], model.name)
        self.assertEqual(float(ledger.amount_usd), 0.03)

    def test_provider_node_uses_configured_active_account(self):
        provider = unique("configured-provider")
        adapter = DeterministicProviderAdapter(provider, cost_usd=0.02)
        registry = ProviderRegistry([adapter])
        project = create_project()
        model = create_model(provider, pricing="0.02")
        create_provider_account(provider, is_default=1)
        configured_account = create_provider_account(provider, is_default=0)
        create_top_up(project.name, "0.10", "Multi-provider configured account credit")
        workflow = create_workflow(
            project,
            provider=provider,
            model_ref=model.name,
            provider_account=configured_account.name,
        )

        start_result = RunService(node_registry=node_registry(registry)).start_run(workflow.name)
        WorkflowExecutor(node_registry=node_registry(registry)).run(start_result.workflow_run)

        provider_job = frappe.get_doc(
            "AI Provider Job",
            frappe.db.get_value("AI Provider Job", {"provider": provider}, "name"),
        )
        self.assertEqual(provider_job.provider_account, configured_account.name)
        self.assertEqual(adapter.submissions[0]["provider_account"], configured_account.name)

    def test_wrong_provider_model_and_account_combinations_reject_before_enqueue(self):
        provider = unique("reject-provider")
        other_provider = unique("reject-other-provider")
        model = create_model(other_provider, pricing="0.01")
        account = create_provider_account(provider)
        other_account = create_provider_account(other_provider)

        model_mismatch = create_workflow(create_project(), provider=provider, model_ref=model.name)
        account_mismatch = create_workflow(
            create_project(),
            provider=provider,
            model_ref=create_model(provider, pricing="0.01").name,
            provider_account=other_account.name,
        )
        inactive_account = create_provider_account(provider, status="DISABLED", is_default=0)
        inactive_workflow = create_workflow(
            create_project(),
            provider=provider,
            model_ref=create_model(provider, pricing="0.01").name,
            provider_account=inactive_account.name,
        )

        self.assert_preflight_rejects_without_provider_job(model_mismatch, "belongs to provider")
        self.assert_preflight_rejects_without_provider_job(account_mismatch, "belongs to provider")
        self.assert_preflight_rejects_without_provider_job(inactive_workflow, "is not active")
        self.assertTrue(account.name)

    def test_engine_core_does_not_import_provider_registry_for_new_adapters(self):
        engine_dir = Path(frappe.get_app_path("slow_ai")) / "engine"
        engine_source = "\n".join(path.read_text() for path in engine_dir.rglob("*.py"))

        self.assertNotIn("slow_ai.providers", engine_source)
        self.assertNotIn("ProviderRegistry", engine_source)

    def assert_preflight_rejects_without_provider_job(self, workflow, message: str) -> None:
        provider_job_count = frappe.db.count("AI Provider Job")
        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertIn(message, str(exc.exception))
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)
        self.assertFalse(frappe.db.exists("AI Workflow Version", {"workflow": workflow.name}))
        self.assertFalse(frappe.db.exists("AI Workflow Run", {"workflow": workflow.name}))

import json
from decimal import Decimal
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
from slow_ai.providers.registry import ProviderRegistry, create_default_provider_registry
from slow_ai.providers.replicate import ReplicateAdapter
from slow_ai.providers.wavespeed import WaveSpeedAdapter
from slow_ai.workers.poll_provider_job import poll_provider_job


SIDE_EFFECT_DOCTYPES = (
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
)

UNSAFE_FRAGMENTS = (
    "provider-contract-secret",
    "provider-contract-account-label",
    "https://provider.example.invalid/raw-result",
    "request_json",
    "response_json",
    "raw_error_json",
    "provider_account",
    "api_key",
    "Authorization",
    "Bearer",
    "Traceback",
    "stack trace",
)


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def assert_count_delta(testcase: FrappeTestCase, before: dict[str, int], expected: dict[str, int]) -> None:
    after = counts()
    for doctype, value in before.items():
        testcase.assertEqual(after[doctype], value + expected.get(doctype, 0), doctype)


def assert_safe_payload(testcase: FrappeTestCase, payload) -> None:
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


class ContractProviderAdapter(ProviderAdapter):
    provider_name = "contract_provider"

    def __init__(
        self,
        *,
        submit_status: str = ProviderJobStatus.WAITING_PROVIDER.value,
        poll_status: str = ProviderJobStatus.SUCCEEDED.value,
        cost_usd: float = 0.07,
    ) -> None:
        self.provider_jobs = ProviderJobRepository()
        self.submit_status = submit_status
        self.poll_status = poll_status
        self.cost_usd = cost_usd
        self.submitted_provider_job_existed = False
        self.submitted_estimated_cost = Decimal("0")
        self.submissions: list[dict[str, Any]] = []
        self.polls: list[str] = []

    def submit_job(self, submission: ProviderSubmission) -> NormalizedProviderResult:
        provider_job = self.provider_jobs.get(submission.provider_job_name)
        self.submitted_provider_job_existed = provider_job.status == ProviderJobStatus.QUEUED.value
        self.submitted_estimated_cost = Decimal(str(provider_job.estimated_cost_usd or 0))
        self.submissions.append(
            {
                "provider_job": provider_job.name,
                "model": submission.model,
                "input_data": dict(submission.input_data),
            }
        )
        self.provider_jobs.mark_submitting(provider_job.name)
        result = self._result(self.submit_status, external_job_id="contract-external-submit")
        self.provider_jobs.apply_result(
            provider_job.name,
            result,
            {
                "id": result.external_job_id,
                "status": result.status,
                "url": "https://provider.example.invalid/raw-result",
                "Authorization": "Bearer provider-contract-secret",
            },
        )
        return result

    def poll_job(self, provider_job_name: str) -> NormalizedProviderResult:
        self.polls.append(provider_job_name)
        result = self._result(self.poll_status, external_job_id="contract-external-poll")
        self.provider_jobs.apply_result(
            provider_job_name,
            result,
            {
                "id": result.external_job_id,
                "status": result.status,
                "url": "https://provider.example.invalid/raw-result",
                "api_key": "provider-contract-secret",
            },
        )
        return result

    def cancel_job(self, provider_job_name: str) -> None:
        self.provider_jobs.mark_cancelled(provider_job_name)

    def normalize_result(self, raw_response: Mapping[str, Any]) -> NormalizedProviderResult:
        return self._result(str(raw_response.get("status") or ProviderJobStatus.WAITING_PROVIDER.value))

    def estimate_cost(self, model: str, input_data: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"currency": "USD", "estimated_cost_usd": self.cost_usd, "model": model}

    def _result(self, status: str, *, external_job_id: str | None = None) -> NormalizedProviderResult:
        if status == ProviderJobStatus.SUCCEEDED.value:
            return NormalizedProviderResult(
                status=status,
                external_job_id=external_job_id,
                outputs=(
                    NormalizedProviderOutput(
                        asset_type="IMAGE",
                        url="https://example.invalid/provider-contract-output.png",
                        mime_type="image/png",
                        metadata={"origin": "provider-contract"},
                    ),
                ),
                cost_usd=self.cost_usd,
            )
        if status in {ProviderJobStatus.FAILED.value, ProviderJobStatus.EXPIRED.value}:
            return NormalizedProviderResult(
                status=status,
                external_job_id=external_job_id,
                error={"type": f"Provider{status.title()}", "message": f"Provider job {status.lower()} safely."},
            )
        if status == ProviderJobStatus.CANCELLED.value:
            return NormalizedProviderResult(
                status=status,
                external_job_id=external_job_id,
                error={"type": "ProviderCancelled", "message": "Provider job cancelled safely."},
            )
        return NormalizedProviderResult(status=status, external_job_id=external_job_id)


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Provider Contract Project"),
            "status": "Open",
        }
    )


def create_provider_account(provider: str):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("provider-contract-account-label"),
            "api_key_secret": "provider-contract-secret",
            "is_default": 1,
            "status": "ACTIVE",
        }
    )


def create_model(provider: str, *, pricing: str = "0.07"):
    return insert_doc(
        {
            "doctype": "AI Model",
            "model_id": unique(f"{provider}/model"),
            "model_slug": unique(f"{provider}-model"),
            "model_name": unique("Provider Contract Model"),
            "provider": provider,
            "status": "ENABLED",
            "category": "provider",
            "node_type": "provider_text_to_image",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "amount_usd": pricing}),
            "capabilities_json": json.dumps({"text_to_image": True}),
            "input_metadata_json": json.dumps({"prompt": "text"}),
            "output_metadata_json": json.dumps({"image": "AI Asset"}),
        }
    )


def create_workflow(project, provider: str, model_name: str):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Provider Contract Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Contract prompt"}},
                    {
                        "id": "provider_1",
                        "type": "provider_text_to_image",
                        "config": {
                            "provider": provider,
                            "model": model_name,
                            "parameters": {"size": "1024x1024"},
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
            "layout_json": "{}",
        }
    )


def registry_for(adapter: ContractProviderAdapter) -> NodeRegistry:
    provider_registry = ProviderRegistry([adapter])
    return NodeRegistry(
        [
            TextPromptNode(),
            ProviderTextToImageNode(provider_registry=provider_registry),
            ExportOutputNode(),
        ]
    )


class TestProviderAdapterContracts(FrappeTestCase):
    def test_default_registry_and_real_adapter_normalizers_are_contract_safe_without_external_calls(self):
        before = counts()
        default_registry = create_default_provider_registry()

        self.assertIn("wavespeed", default_registry.provider_names())
        self.assertIn("replicate", default_registry.provider_names())
        self._assert_real_adapter_contract(WaveSpeedAdapter())
        self._assert_real_adapter_contract(ReplicateAdapter())
        assert_count_delta(self, before, {})

    def test_deterministic_adapter_submit_then_poll_success_materializes_expected_records_safely(self):
        adapter = ContractProviderAdapter(
            submit_status=ProviderJobStatus.WAITING_PROVIDER.value,
            poll_status=ProviderJobStatus.SUCCEEDED.value,
            cost_usd=0.07,
        )
        adapter.provider_name = unique("contract-provider")
        project = create_project()
        model = create_model(adapter.provider_name)
        create_provider_account(adapter.provider_name)
        create_top_up(project.name, "0.50", "Provider adapter contract credit")
        workflow = create_workflow(project, adapter.provider_name, model.name)
        node_registry = registry_for(adapter)

        before = counts()
        start = RunService(node_registry=node_registry).start_run(workflow.name)
        WorkflowExecutor(node_registry=node_registry).run(start.workflow_run)
        provider_job = frappe.get_doc(
            "AI Provider Job",
            frappe.db.get_value("AI Provider Job", {"provider": adapter.provider_name}, "name"),
        )
        self.assertTrue(adapter.submitted_provider_job_existed)
        self.assertEqual(adapter.submitted_estimated_cost, Decimal("0.07"))
        self.assertEqual(provider_job.status, ProviderJobStatus.WAITING_PROVIDER.value)
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job.name}), 0)

        polled = poll_provider_job(
            provider_job.name,
            provider_registry=ProviderRegistry([adapter]),
            enqueue_resume=False,
        )

        provider_job.reload()
        node_run = frappe.get_doc("AI Node Run", provider_job.node_run)
        self.assertEqual(polled["status"], ProviderJobStatus.SUCCEEDED.value)
        self.assertEqual(provider_job.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertEqual(node_run.status, "SUCCEEDED")
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job.name}), 1)
        self.assertEqual(
            frappe.db.count("AI Credit Ledger", {"provider_job": provider_job.name, "ledger_type": "DEBIT"}),
            1,
        )
        assert_count_delta(
            self,
            before,
            {
                "AI Workflow Version": 1,
                "AI Workflow Run": 1,
                "AI Node Run": 3,
                "AI Provider Job": 1,
                "AI Asset": 1,
                "AI Credit Ledger": 3,
            },
        )
        self._assert_safe_run_payloads(start.workflow_run)

    def test_waiting_failure_cancelled_and_expired_poll_paths_are_bounded_and_do_not_create_outputs(self):
        for terminal_status in (
            ProviderJobStatus.WAITING_PROVIDER.value,
            ProviderJobStatus.FAILED.value,
            ProviderJobStatus.CANCELLED.value,
            ProviderJobStatus.EXPIRED.value,
        ):
            with self.subTest(terminal_status=terminal_status):
                adapter, workflow_run, provider_job = self._prepare_waiting_provider_job(terminal_status)
                before_asset_count = frappe.db.count("AI Asset", {"source_provider_job": provider_job.name})
                before_debit_count = frappe.db.count(
                    "AI Credit Ledger",
                    {"provider_job": provider_job.name, "ledger_type": "DEBIT"},
                )

                result = poll_provider_job(
                    provider_job.name,
                    provider_registry=ProviderRegistry([adapter]),
                    enqueue_resume=False,
                )

                provider_job.reload()
                node_run = frappe.get_doc("AI Node Run", provider_job.node_run)
                self.assertEqual(result["status"], terminal_status)
                self.assertEqual(provider_job.status, terminal_status)
                self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job.name}), before_asset_count)
                self.assertEqual(
                    frappe.db.count("AI Credit Ledger", {"provider_job": provider_job.name, "ledger_type": "DEBIT"}),
                    before_debit_count,
                )
                if terminal_status == ProviderJobStatus.WAITING_PROVIDER.value:
                    self.assertEqual(node_run.status, "WAITING_PROVIDER")
                elif terminal_status == ProviderJobStatus.CANCELLED.value:
                    self.assertEqual(node_run.status, "CANCELLED")
                else:
                    self.assertEqual(node_run.status, "FAILED")
                self._assert_safe_run_payloads(workflow_run)

    def _prepare_waiting_provider_job(self, poll_status: str):
        provider = unique("contract-provider")
        adapter = ContractProviderAdapter(
            submit_status=ProviderJobStatus.WAITING_PROVIDER.value,
            poll_status=poll_status,
            cost_usd=0.02,
        )
        adapter.provider_name = provider
        project = create_project()
        model = create_model(provider, pricing="0.02")
        create_provider_account(provider)
        create_top_up(project.name, "0.20", "Provider adapter terminal credit")
        workflow = create_workflow(project, provider, model.name)
        node_registry = registry_for(adapter)
        start = RunService(node_registry=node_registry).start_run(workflow.name)
        WorkflowExecutor(node_registry=node_registry).run(start.workflow_run)
        provider_job = frappe.get_doc(
            "AI Provider Job",
            frappe.db.get_value("AI Provider Job", {"provider": provider}, "name"),
        )
        self.assertEqual(provider_job.status, ProviderJobStatus.WAITING_PROVIDER.value)
        return adapter, start.workflow_run, provider_job

    def _assert_real_adapter_contract(self, adapter: ProviderAdapter) -> None:
        self.assertTrue(adapter.provider_name)
        estimate = adapter.estimate_cost("provider-contract/model", {"prompt": "safe prompt"})
        self.assertEqual(estimate.get("currency"), "USD")
        assert_safe_payload(self, estimate)

        success_raw = self._success_raw(adapter.provider_name)
        success = adapter.normalize_result(success_raw)
        self.assertEqual(success.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertEqual(len(success.outputs), 1)
        self.assertTrue(success.outputs[0].url.startswith("https://example.invalid/"))

        waiting = adapter.normalize_result(self._waiting_raw(adapter.provider_name))
        self.assertIn(waiting.status, {ProviderJobStatus.SUBMITTED.value, ProviderJobStatus.WAITING_PROVIDER.value})
        self.assertFalse(waiting.outputs)

        failed = adapter.normalize_result(self._failed_raw(adapter.provider_name))
        self.assertEqual(failed.status, ProviderJobStatus.FAILED.value)
        self.assertTrue(failed.error)

        cancelled = adapter.normalize_result(self._cancelled_raw(adapter.provider_name))
        self.assertEqual(cancelled.status, ProviderJobStatus.CANCELLED.value)
        assert_safe_payload(
            self,
            {
                "estimate": estimate,
                "success": success,
                "waiting": waiting,
                "failed": failed,
                "cancelled": cancelled,
            },
        )

    def _success_raw(self, provider: str) -> dict[str, Any]:
        if provider == "wavespeed":
            return {
                "code": 200,
                "data": {
                    "id": "contract-wavespeed-success",
                    "status": "completed",
                    "outputs": ["https://example.invalid/wavespeed-contract.png"],
                    "cost_usd": 0.01,
                },
            }
        return {
            "id": "contract-replicate-success",
            "status": "succeeded",
            "output": ["https://example.invalid/replicate-contract.png"],
            "metrics": {"cost_usd": 0.01},
        }

    def _waiting_raw(self, provider: str) -> dict[str, Any]:
        if provider == "wavespeed":
            return {"code": 200, "data": {"id": "contract-wavespeed-waiting", "status": "processing"}}
        return {"id": "contract-replicate-waiting", "status": "processing"}

    def _failed_raw(self, provider: str) -> dict[str, Any]:
        if provider == "wavespeed":
            return {"code": 500, "message": "Provider request failed safely."}
        return {"code": 500, "detail": "Provider request failed safely."}

    def _cancelled_raw(self, provider: str) -> dict[str, Any]:
        if provider == "wavespeed":
            return {"code": 200, "data": {"id": "contract-wavespeed-cancelled", "status": "cancelled"}}
        return {"id": "contract-replicate-cancelled", "status": "canceled"}

    def _assert_safe_run_payloads(self, workflow_run: str) -> None:
        for method in (
            "slow_ai.api.runs.get_run_status",
            "slow_ai.api.runs.get_history",
            "slow_ai.api.runs.get_run_timeline",
        ):
            payload = frappe.call(method, workflow_run=workflow_run)
            assert_safe_payload(self, payload)

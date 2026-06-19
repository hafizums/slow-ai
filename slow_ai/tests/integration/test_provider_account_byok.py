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
from slow_ai.providers.wavespeed.auth import WaveSpeedAuth


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


class RecordingProviderAdapter(ProviderAdapter):
    def __init__(self, provider_name: str, *, cost_usd: float = 0.02) -> None:
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
            external_job_id=unique("byok-provider-job"),
            outputs=(
                NormalizedProviderOutput(
                    asset_type="IMAGE",
                    url="https://example.invalid/byok.png",
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
            "project_name": unique("BYOK Project"),
            "status": "Open",
        }
    )


def create_model(provider: str, *, pricing: str = "0.02"):
    return insert_doc(
        {
            "doctype": "AI Model",
            "model_id": unique(f"{provider}/model"),
            "model_slug": unique(f"{provider}-slug"),
            "model_name": "BYOK Test Model",
            "provider": provider,
            "status": "ENABLED",
            "node_type": "provider_text_to_image",
            "category": "provider",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "amount_usd": pricing}),
        }
    )


def create_account(
    provider: str,
    *,
    project: str | None = None,
    user: str | None = None,
    is_default: int = 1,
    status: str = "ACTIVE",
):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("BYOK Account"),
            "project": project,
            "user": user,
            "api_key_secret": "byok-test-secret",
            "is_default": is_default,
            "status": status,
        }
    )


def create_workflow(project, *, provider: str, model_ref: str, provider_account: str | None = None):
    config = {
        "provider": provider,
        "model": model_ref,
        "parameters": {"size": "1024*1024"},
    }
    if provider_account:
        config["provider_account"] = provider_account
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("BYOK Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "BYOK prompt"}},
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


class TestProviderAccountBYOK(FrappeTestCase):
    def test_create_list_and_get_provider_account_apis_are_secret_safe(self):
        provider = unique("byok-safe-provider")
        project = create_project()
        secret = unique("byok-secret")
        provider_job_count = frappe.db.count("AI Provider Job")

        created = frappe.call(
            "slow_ai.api.provider_accounts.create_account",
            provider=provider,
            account_label="BYOK Safe Account",
            api_key=secret,
            project=project.name,
            is_default=1,
        )
        listed = frappe.call("slow_ai.api.provider_accounts.list_accounts", provider=provider)
        fetched = frappe.call(
            "slow_ai.api.provider_accounts.get_account",
            account=created["account"]["name"],
        )

        account = frappe.get_doc("AI Provider Account", created["account"]["name"])
        self.assertEqual(account.get_password("api_key_secret"), secret)
        serialized_payloads = json.dumps({"created": created, "listed": listed, "fetched": fetched}, default=str)
        self.assertNotIn(secret, serialized_payloads)
        self.assertNotIn("api_key_secret", serialized_payloads)
        self.assertNotIn("api_key", serialized_payloads)
        self.assertEqual(created["account"]["project"], project.name)
        self.assertEqual(created["account"]["provider"], provider)
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)

    def test_set_default_only_updates_matching_provider_scope(self):
        provider = unique("byok-default-provider")
        project = create_project()
        first = create_account(provider, project=project.name, is_default=1)
        second = create_account(provider, project=project.name, is_default=0)
        other_project = create_project()
        other_scope_default = create_account(provider, project=other_project.name, is_default=1)

        result = frappe.call("slow_ai.api.provider_accounts.set_default", account=second.name)

        first.reload()
        second.reload()
        other_scope_default.reload()
        self.assertEqual(result["account"]["name"], second.name)
        self.assertEqual(first.is_default, 0)
        self.assertEqual(second.is_default, 1)
        self.assertEqual(other_scope_default.is_default, 1)

    def test_default_scoped_account_resolution_persists_provider_job_account(self):
        provider = unique("byok-default-run-provider")
        adapter = RecordingProviderAdapter(provider)
        registry = ProviderRegistry([adapter])
        project = create_project()
        model = create_model(provider)
        account = create_account(provider, project=project.name, is_default=1)
        create_top_up(project.name, "0.10", "BYOK default account credit")
        workflow = create_workflow(project, provider=provider, model_ref=model.model_slug)

        start_result = RunService(node_registry=node_registry(registry)).start_run(workflow.name)
        WorkflowExecutor(node_registry=node_registry(registry)).run(start_result.workflow_run)

        provider_job = frappe.get_doc(
            "AI Provider Job",
            frappe.db.get_value("AI Provider Job", {"provider": provider}, "name"),
        )
        self.assertEqual(provider_job.provider_account, account.name)
        self.assertEqual(adapter.submissions[0]["provider_account"], account.name)
        self.assertEqual(provider_job.model, model.name)

    def test_configured_scoped_account_resolution_persists_provider_job_account(self):
        provider = unique("byok-configured-run-provider")
        adapter = RecordingProviderAdapter(provider)
        registry = ProviderRegistry([adapter])
        project = create_project()
        model = create_model(provider)
        create_account(provider, project=project.name, is_default=1)
        configured = create_account(provider, project=project.name, is_default=0)
        create_top_up(project.name, "0.10", "BYOK configured account credit")
        workflow = create_workflow(
            project,
            provider=provider,
            model_ref=model.name,
            provider_account=configured.name,
        )

        start_result = RunService(node_registry=node_registry(registry)).start_run(workflow.name)
        WorkflowExecutor(node_registry=node_registry(registry)).run(start_result.workflow_run)

        provider_job = frappe.get_doc(
            "AI Provider Job",
            frappe.db.get_value("AI Provider Job", {"provider": provider}, "name"),
        )
        self.assertEqual(provider_job.provider_account, configured.name)
        self.assertEqual(adapter.submissions[0]["provider_account"], configured.name)

    def test_inactive_mismatch_and_unauthorized_accounts_reject_before_enqueue(self):
        provider = unique("byok-reject-provider")
        other_provider = unique("byok-other-provider")
        model = create_model(provider)
        project = create_project()
        other_project = create_project()
        inactive = create_account(provider, project=project.name, status="DISABLED", is_default=0)
        mismatched = create_account(other_provider, project=project.name, is_default=0)
        other_project_account = create_account(provider, project=other_project.name, is_default=0)
        user_scoped_account = create_account(provider, project=project.name, user="Guest", is_default=0)

        self.assert_preflight_rejects_without_side_effects(
            create_workflow(project, provider=provider, model_ref=model.name, provider_account=inactive.name),
            "is not active",
        )
        self.assert_preflight_rejects_without_side_effects(
            create_workflow(project, provider=provider, model_ref=model.name, provider_account=mismatched.name),
            "belongs to provider",
        )
        self.assert_preflight_rejects_without_side_effects(
            create_workflow(
                project,
                provider=provider,
                model_ref=model.name,
                provider_account=other_project_account.name,
            ),
            "not allowed",
        )
        self.assert_preflight_rejects_without_side_effects(
            create_workflow(
                project,
                provider=provider,
                model_ref=model.name,
                provider_account=user_scoped_account.name,
            ),
            "not allowed",
        )

    def test_wavespeed_auth_reads_byok_secret_server_side_only(self):
        provider = "wavespeed"
        secret = unique("wavespeed-byok-secret")
        created = frappe.call(
            "slow_ai.api.provider_accounts.create_account",
            provider=provider,
            account_label="WaveSpeed BYOK Account",
            api_key=secret,
            is_default=0,
        )

        api_key = WaveSpeedAuth().get_api_key(created["account"]["name"])
        fetched = frappe.call(
            "slow_ai.api.provider_accounts.get_account",
            account=created["account"]["name"],
        )

        self.assertEqual(api_key, secret)
        self.assertNotIn(secret, json.dumps(fetched, default=str))
        self.assertNotIn("api_key_secret", json.dumps(fetched, default=str))

    def assert_preflight_rejects_without_side_effects(self, workflow, message: str) -> None:
        provider_job_count = frappe.db.count("AI Provider Job")
        workflow_version_count = frappe.db.count("AI Workflow Version", {"workflow": workflow.name})
        workflow_run_count = frappe.db.count("AI Workflow Run", {"workflow": workflow.name})

        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertIn(message, str(exc.exception))
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)
        self.assertEqual(frappe.db.count("AI Workflow Version", {"workflow": workflow.name}), workflow_version_count)
        self.assertEqual(frappe.db.count("AI Workflow Run", {"workflow": workflow.name}), workflow_run_count)

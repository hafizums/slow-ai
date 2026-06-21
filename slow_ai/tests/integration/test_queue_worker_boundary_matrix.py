import json
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date
from frappe.utils import now_datetime

from slow_ai.application.billing import create_top_up
from slow_ai.application.run_service import RunService
from slow_ai.domain.exceptions import RunPreflightError
from slow_ai.domain.status import ProviderJobStatus
from slow_ai.infrastructure.provider_jobs import ProviderJobRepository
from slow_ai.node_registry.nodes.export_output import ExportOutputNode
from slow_ai.node_registry.nodes.provider import ProviderTextToImageNode
from slow_ai.node_registry.nodes.text_prompt import TextPromptNode
from slow_ai.node_registry.registry import NodeRegistry
from slow_ai.providers.contracts import NormalizedProviderOutput
from slow_ai.providers.contracts import NormalizedProviderResult
from slow_ai.providers.contracts import ProviderAdapter
from slow_ai.providers.contracts import ProviderSubmission
from slow_ai.providers.registry import ProviderRegistry
from slow_ai.workers.poll_provider_job import poll_pending_provider_jobs
from slow_ai.workers.poll_provider_job import poll_provider_job
from slow_ai.workers.resume_workflow import resume_workflow
from slow_ai.workers.run_workflow import run_workflow


SIDE_EFFECT_DOCTYPES = (
    "AI Workflow",
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
)

MUTATION_SNAPSHOT_FIELDS = {
    "AI Workflow": ["name", "project", "title", "status", "modified"],
    "AI Workflow Version": ["name", "workflow", "snapshot_hash", "modified"],
    "AI Workflow Run": ["name", "workflow", "project", "status", "error_json", "modified"],
    "AI Node Run": ["name", "workflow_run", "status", "provider_job", "output_json", "error_json", "modified"],
    "AI Provider Job": [
        "name",
        "node_run",
        "provider",
        "status",
        "external_job_id",
        "poll_attempts",
        "last_polled_at",
        "raw_error_json",
        "modified",
    ],
    "AI Asset": ["name", "project", "source_workflow_run", "source_provider_job", "modified"],
    "AI Credit Ledger": ["name", "project", "workflow_run", "provider_job", "ledger_type", "amount_usd", "modified"],
    "AI Tool Run Share": ["name", "workflow_run", "status", "modified"],
}

UNSAFE_FRAGMENTS = (
    "queue-boundary-secret",
    "https://provider.example.invalid",
    "provider_account",
    "api_key",
    "Authorization",
    "Bearer",
    "request_json",
    "response_json",
    "raw_error_json",
    "draft_nodes_json",
    "draft_edges_json",
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def _record_counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def _mutation_snapshot() -> dict[str, list[dict]]:
    snapshot = {}
    for doctype, fields in MUTATION_SNAPSHOT_FIELDS.items():
        snapshot[doctype] = [dict(row) for row in frappe.get_all(doctype, fields=fields, order_by="name asc")]
    return json.loads(json.dumps(snapshot, default=str))


def _assert_no_side_effects(testcase: FrappeTestCase, before_counts: dict[str, int], before_snapshot: dict[str, list[dict]]):
    testcase.assertEqual(_record_counts(), before_counts)
    testcase.assertEqual(_mutation_snapshot(), before_snapshot)


def _assert_safe_payload(testcase: FrappeTestCase, payload):
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


def _create_project():
    return _insert_doc(
        {
            "doctype": "AI Project",
            "project_name": _unique("Queue Boundary Project"),
            "status": "Open",
        }
    )


def _text_nodes():
    return [
        {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Queue boundary prompt"}},
        {"id": "output_1", "type": "export_output", "config": {}},
    ]


def _text_edges():
    return [
        {
            "id": "edge_1",
            "source": "prompt_1",
            "source_port": "text",
            "target": "output_1",
            "target_port": "text",
        }
    ]


def _create_text_workflow(project):
    return frappe.get_doc(
        {
            "doctype": "AI Workflow",
            "project": project.name,
            "title": _unique("Queue Boundary Text Workflow"),
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(_text_nodes()),
            "draft_edges_json": json.dumps(_text_edges()),
            "layout_json": "{}",
        }
    ).insert(ignore_permissions=True)


def _create_model(provider: str, *, pricing: str = "0.05"):
    return _insert_doc(
        {
            "doctype": "AI Model",
            "model_id": _unique(f"{provider}/model"),
            "model_name": "Queue Boundary Model",
            "provider": provider,
            "status": "ENABLED",
            "modality": "TEXT_TO_IMAGE",
            "node_type": "provider_text_to_image",
            "category": "provider",
            "pricing_json": json.dumps({"unit": "run", "amount_usd": pricing}),
        }
    )


def _create_provider_account(provider: str, *, status: str = "ACTIVE", project: str | None = None):
    return _insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": _unique("Queue Boundary Provider Account"),
            "api_key_secret": "queue-boundary-secret",
            "project": project,
            "is_default": 1,
            "status": status,
        }
    )


def _provider_nodes(provider: str, model: str, provider_account: str | None = None):
    config = {"provider": provider, "model": model}
    if provider_account:
        config["provider_account"] = provider_account
    return [
        {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Queue boundary provider prompt"}},
        {"id": "provider_1", "type": "provider_text_to_image", "config": config},
        {"id": "output_1", "type": "export_output", "config": {}},
    ]


def _provider_edges():
    return [
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


def _create_provider_workflow(project, provider: str, model: str, provider_account: str | None = None):
    return _insert_doc(
        {
            "doctype": "AI Workflow",
            "project": project.name,
            "title": _unique("Queue Boundary Provider Workflow"),
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(_provider_nodes(provider, model, provider_account)),
            "draft_edges_json": json.dumps(_provider_edges()),
            "layout_json": "{}",
        }
    )


class BoundaryProviderAdapter(ProviderAdapter):
    def __init__(
        self,
        provider_name: str,
        *,
        submit_status: str = ProviderJobStatus.SUCCEEDED.value,
        poll_status: str = ProviderJobStatus.SUCCEEDED.value,
    ) -> None:
        self.provider_name = provider_name
        self.submit_status = submit_status
        self.poll_status = poll_status
        self.provider_jobs = ProviderJobRepository()
        self.submitted: list[str] = []
        self.polled: list[str] = []

    def submit_job(self, submission: ProviderSubmission) -> NormalizedProviderResult:
        self.submitted.append(submission.provider_job_name)
        self.provider_jobs.mark_submitting(submission.provider_job_name)
        result = NormalizedProviderResult(
            status=self.submit_status,
            external_job_id=f"{self.provider_name}-external",
            outputs=(
                NormalizedProviderOutput(
                    asset_type="IMAGE",
                    url="https://safe-assets.example.invalid/queue-boundary.png",
                    mime_type="image/png",
                    metadata={"origin": "queue-boundary"},
                ),
            )
            if self.submit_status == ProviderJobStatus.SUCCEEDED.value
            else (),
            cost_usd=0.05 if self.submit_status == ProviderJobStatus.SUCCEEDED.value else 0,
        )
        self.provider_jobs.apply_result(
            submission.provider_job_name,
            result,
            {
                "data": {
                    "id": result.external_job_id,
                    "status": result.status,
                    "Authorization": "Bearer queue-boundary-secret",
                    "url": "https://provider.example.invalid/raw",
                }
            },
        )
        return result

    def poll_job(self, provider_job_name: str) -> NormalizedProviderResult:
        self.polled.append(provider_job_name)
        result = NormalizedProviderResult(
            status=self.poll_status,
            external_job_id=f"{self.provider_name}-external",
            outputs=(
                NormalizedProviderOutput(
                    asset_type="IMAGE",
                    url="https://safe-assets.example.invalid/queue-boundary-polled.png",
                    mime_type="image/png",
                ),
            )
            if self.poll_status == ProviderJobStatus.SUCCEEDED.value
            else (),
            cost_usd=0.05 if self.poll_status == ProviderJobStatus.SUCCEEDED.value else 0,
        )
        self.provider_jobs.apply_result(
            provider_job_name,
            result,
            {
                "data": {
                    "id": result.external_job_id,
                    "status": result.status,
                    "api_key": "queue-boundary-secret",
                    "url": "https://provider.example.invalid/poll",
                }
            },
        )
        return result

    def cancel_job(self, provider_job_name: str) -> None:
        self.provider_jobs.mark_cancelled(provider_job_name)

    def normalize_result(self, raw_response: Mapping[str, Any]) -> NormalizedProviderResult:
        return NormalizedProviderResult(
            status=raw_response.get("status") or self.poll_status,
            external_job_id=raw_response.get("external_job_id") or f"{self.provider_name}-external",
            outputs=(),
            cost_usd=0,
        )

    def estimate_cost(self, model: str, input_data: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"currency": "USD", "estimated_cost_usd": 0.05, "model": model}


def _node_registry(adapter: BoundaryProviderAdapter) -> NodeRegistry:
    provider_registry = ProviderRegistry([adapter])
    return NodeRegistry(
        [
            TextPromptNode(),
            ProviderTextToImageNode(provider_registry=provider_registry),
            ExportOutputNode(),
        ]
    )


def _create_provider_run(status: str = "WAITING_PROVIDER"):
    provider = _unique("queue-boundary-provider")
    adapter = BoundaryProviderAdapter(provider, submit_status=ProviderJobStatus.WAITING_PROVIDER.value)
    project = _create_project()
    model = _create_model(provider)
    _create_provider_account(provider, project=project.name)
    create_top_up(project.name, "1.00", "Queue boundary credit")
    workflow = _create_provider_workflow(project, provider, model.name)
    start_result = RunService(node_registry=_node_registry(adapter)).start_run(workflow.name)
    if status == "WAITING_PROVIDER":
        run_workflow_with_registry(start_result.workflow_run, adapter)
    return project, workflow, start_result, adapter


def run_workflow_with_registry(workflow_run: str, adapter: BoundaryProviderAdapter):
    from slow_ai.engine.executor import WorkflowExecutor

    WorkflowExecutor(node_registry=_node_registry(adapter)).run(workflow_run)


class TestQueueWorkerBoundaryMatrix(FrappeTestCase):
    def tearDown(self):
        frappe.set_user("Administrator")

    def test_read_apis_and_queue_status_do_not_execute_or_poll_or_mutate_worker_state(self):
        project, _, result, adapter = _create_provider_run()
        provider_job = frappe.get_doc(
            "AI Provider Job",
            frappe.db.get_value("AI Provider Job", {"provider": adapter.provider_name}, "name"),
        )
        frappe.db.set_value(
            "AI Provider Job",
            provider_job.name,
            {
                "request_json": json.dumps({"Authorization": "Bearer queue-boundary-secret"}),
                "response_json": json.dumps({"url": "https://provider.example.invalid/response"}),
                "raw_error_json": json.dumps({"api_key": "queue-boundary-secret"}),
            },
        )
        before_counts = _record_counts()
        before_snapshot = _mutation_snapshot()
        adapter.polled.clear()

        payloads = [
            frappe.call("slow_ai.api.runs.get_run_status", workflow_run=result.workflow_run),
            frappe.call("slow_ai.api.runs.get_history", workflow_run=result.workflow_run),
            frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=result.workflow_run),
            frappe.call("slow_ai.api.queue.get_queue_status"),
            frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=result.workflow_run),
            frappe.call("slow_ai.api.public_tools.get_run_output_gallery", workflow_run=result.workflow_run),
        ]

        self.assertEqual(adapter.polled, [])
        for payload in payloads:
            _assert_safe_payload(self, payload)
        _assert_no_side_effects(self, before_counts, before_snapshot)
        self.assertEqual(frappe.db.get_value("AI Workflow Run", result.workflow_run, "status"), "WAITING_PROVIDER")
        self.assertEqual(frappe.db.get_value("AI Provider Job", provider_job.name, "poll_attempts") or 0, 0)

    def test_run_workflow_worker_is_the_only_path_that_creates_provider_job_from_started_run(self):
        provider = _unique("queue-boundary-submit-provider")
        adapter = BoundaryProviderAdapter(provider)
        project = _create_project()
        model = _create_model(provider)
        _create_provider_account(provider, project=project.name)
        create_top_up(project.name, "1.00", "Queue boundary provider execution credit")
        workflow = _create_provider_workflow(project, provider, model.name)
        start_result = RunService(node_registry=_node_registry(adapter)).start_run(workflow.name)

        self.assertFalse(frappe.db.exists("AI Provider Job", {"provider": provider}))
        before_worker = _record_counts()
        run_workflow_with_registry(start_result.workflow_run, adapter)

        provider_job_name = frappe.db.get_value("AI Provider Job", {"provider": provider}, "name")
        self.assertTrue(provider_job_name)
        self.assertEqual(adapter.submitted, [provider_job_name])
        self.assertEqual(frappe.db.count("AI Provider Job", {"provider": provider}), 1)
        self.assertGreater(frappe.db.count("AI Asset", {"source_provider_job": provider_job_name}), 0)
        self.assertGreater(frappe.db.count("AI Credit Ledger", {"provider_job": provider_job_name}), 0)
        self.assertEqual(before_worker["AI Workflow"], _record_counts()["AI Workflow"])
        self.assertEqual(frappe.db.get_value("AI Workflow Run", start_result.workflow_run, "status"), "SUCCEEDED")

    def test_terminal_run_worker_and_resume_invocations_are_no_ops(self):
        workflow = _create_text_workflow(_create_project())
        start_result = RunService().start_run(workflow.name)
        run_workflow(start_result.workflow_run)
        before_counts = _record_counts()
        before_statuses = {
            "run": frappe.db.get_value("AI Workflow Run", start_result.workflow_run, "status"),
            "nodes": frappe.get_all(
                "AI Node Run",
                filters={"workflow_run": start_result.workflow_run},
                fields=["name", "status", "output_json"],
                order_by="name asc",
            ),
        }

        run_workflow(start_result.workflow_run)
        resume_workflow(start_result.workflow_run)

        self.assertEqual(_record_counts(), before_counts)
        self.assertEqual(frappe.db.get_value("AI Workflow Run", start_result.workflow_run, "status"), before_statuses["run"])
        self.assertEqual(
            [
                dict(row)
                for row in frappe.get_all(
                    "AI Node Run",
                    filters={"workflow_run": start_result.workflow_run},
                    fields=["name", "status", "output_json"],
                    order_by="name asc",
                )
            ],
            [dict(row) for row in before_statuses["nodes"]],
        )

    def test_poll_pending_provider_jobs_processes_only_eligible_jobs_and_skips_no_external_id(self):
        project, _, result, adapter = _create_provider_run()
        node_run = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": result.workflow_run, "node_id": "provider_1"},
            "name",
        )
        model = frappe.db.get_value("AI Model", {"provider": adapter.provider_name}, "name")
        eligible = frappe.db.get_value("AI Provider Job", {"node_run": node_run}, "name")
        no_external = _insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run,
                "provider": adapter.provider_name,
                "model": model,
                "status": "SUBMITTED",
                "idempotency_key": _unique("queue-no-external"),
                "request_json": "{}",
            }
        )
        terminal = _insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run,
                "provider": adapter.provider_name,
                "model": model,
                "status": "SUCCEEDED",
                "external_job_id": "terminal-external",
                "idempotency_key": _unique("queue-terminal"),
                "request_json": "{}",
            }
        )
        queued = _insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run,
                "provider": adapter.provider_name,
                "model": model,
                "status": "QUEUED",
                "external_job_id": "queued-external",
                "idempotency_key": _unique("queue-queued"),
                "request_json": "{}",
            }
        )
        adapter.polled.clear()

        result_payload = poll_pending_provider_jobs(
            provider=adapter.provider_name,
            provider_registry=ProviderRegistry([adapter]),
        )

        self.assertEqual(adapter.polled, [eligible])
        self.assertEqual([row["provider_job"] for row in result_payload["polled"]], [eligible])
        self.assertEqual(result_payload["skipped"], [no_external.name])
        self.assertEqual(frappe.db.get_value("AI Provider Job", eligible, "status"), "SUCCEEDED")
        self.assertEqual(frappe.db.get_value("AI Provider Job", no_external.name, "status"), "SUBMITTED")
        self.assertEqual(frappe.db.get_value("AI Provider Job", terminal.name, "status"), "SUCCEEDED")
        self.assertEqual(frappe.db.get_value("AI Provider Job", queued.name, "status"), "QUEUED")

    def test_cancelled_run_and_timeout_policy_stop_polling_without_provider_call_or_resume(self):
        project, _, result, adapter = _create_provider_run()
        provider_job = frappe.get_doc(
            "AI Provider Job",
            frappe.db.get_value("AI Provider Job", {"provider": adapter.provider_name}, "name"),
        )
        frappe.db.set_value("AI Workflow Run", result.workflow_run, "status", "CANCELLED")
        adapter.polled.clear()
        before_cancel_counts = _record_counts()

        cancelled = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertEqual(cancelled["queue_job_id"], None)
        self.assertEqual(adapter.polled, [])
        self.assertEqual(frappe.db.get_value("AI Workflow Run", result.workflow_run, "status"), "CANCELLED")
        self.assertEqual(frappe.db.count("AI Provider Job"), before_cancel_counts["AI Provider Job"])
        self.assertEqual(frappe.db.count("AI Asset"), before_cancel_counts["AI Asset"])

        project, _, result, adapter = _create_provider_run()
        provider_job = frappe.get_doc(
            "AI Provider Job",
            frappe.db.get_value("AI Provider Job", {"provider": adapter.provider_name}, "name"),
        )
        frappe.db.set_value(
            "AI Provider Job",
            provider_job.name,
            {"submitted_at": add_to_date(now_datetime(), seconds=-120), "timeout_seconds": 1},
        )
        adapter.polled.clear()
        before_timeout_counts = _record_counts()

        expired = poll_provider_job(provider_job.name, provider_registry=ProviderRegistry([adapter]))

        self.assertEqual(expired["status"], "EXPIRED")
        self.assertEqual(expired["queue_job_id"], None)
        self.assertEqual(adapter.polled, [])
        self.assertEqual(frappe.db.get_value("AI Workflow Run", result.workflow_run, "status"), "EXPIRED")
        self.assertEqual(frappe.db.count("AI Provider Job"), before_timeout_counts["AI Provider Job"])
        self.assertEqual(frappe.db.count("AI Asset"), before_timeout_counts["AI Asset"])

    def test_invalid_provider_account_preflight_rejects_before_worker_provider_side_effects(self):
        provider = _unique("queue-boundary-inactive-provider")
        project = _create_project()
        model = _create_model(provider)
        inactive = _create_provider_account(provider, status="DISABLED", project=project.name)
        create_top_up(project.name, "1.00", "Queue boundary inactive account credit")
        workflow = _create_provider_workflow(project, provider, model.name, inactive.name)
        before = _record_counts()

        with self.assertRaises(RunPreflightError):
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertEqual(frappe.db.count("AI Workflow Version"), before["AI Workflow Version"])
        self.assertEqual(frappe.db.count("AI Workflow Run"), before["AI Workflow Run"])
        self.assertEqual(frappe.db.count("AI Node Run"), before["AI Node Run"])
        self.assertEqual(frappe.db.count("AI Provider Job"), before["AI Provider Job"])
        self.assertEqual(frappe.db.count("AI Asset"), before["AI Asset"])
        self.assertEqual(frappe.db.count("AI Credit Ledger"), before["AI Credit Ledger"])

    def test_api_and_frontend_sources_do_not_import_workers_or_providers_in_read_paths(self):
        app_path = Path(frappe.get_app_path("slow_ai"))
        api_sources = [
            app_path / "api/runs.py",
            app_path / "api/queue.py",
            app_path / "api/public_tools.py",
            app_path / "application/runs.py",
            app_path / "application/queue.py",
            app_path / "application/public_tools.py",
            app_path / "application/run_outputs.py",
        ]
        frontend_sources = [
            app_path / "slow_ai/page/slow_ai_canvas/slow_ai_canvas.js",
            app_path / "slow_ai/page/slow_ai_tools/slow_ai_tools.js",
            app_path / "www/slow-ai/shared.html",
        ]

        for source_path in api_sources:
            source = source_path.read_text()
            self.assertNotIn("slow_ai.workers", source, str(source_path))
            self.assertNotIn("WorkflowExecutor", source, str(source_path))
            self.assertNotIn("poll_provider_job", source, str(source_path))
            self.assertNotIn("frappe.enqueue", source, str(source_path))

        forbidden_frontend = (
            "slow_ai.workers",
            "run_workflow",
            "poll_provider_job",
            "frappe.enqueue",
            "frappe.db",
            "ProviderAdapter",
            "ProviderRegistry",
            "api.wavespeed.ai",
            "api.replicate.com",
            "request_json",
            "response_json",
            "raw_error_json",
            "api_key_secret",
            "Authorization: Bearer",
        )
        for source_path in frontend_sources:
            source = source_path.read_text()
            for fragment in forbidden_frontend:
                self.assertNotIn(fragment, source, f"{fragment} in {source_path}")

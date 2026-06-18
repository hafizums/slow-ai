import json
from typing import Any, Mapping
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.run_service import RunService
from slow_ai.domain.status import ProviderJobStatus
from slow_ai.infrastructure.provider_jobs import ProviderJobRepository
from slow_ai.infrastructure.realtime import NODE_RUN_EVENT, PROVIDER_JOB_EVENT, WORKFLOW_RUN_EVENT
from slow_ai.providers.contracts import NormalizedProviderResult, ProviderAdapter, ProviderSubmission
from slow_ai.providers.registry import ProviderRegistry
from slow_ai.workers.poll_provider_job import poll_pending_provider_jobs, poll_provider_job
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
            "project_name": unique("Worker Project"),
            "status": "Open",
        }
    )


def create_text_workflow(project):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Worker Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Worker text"}},
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


def event_names() -> set[str]:
    return {entry[0] for entry in frappe.local.realtime_log}


class PollingProviderAdapter(ProviderAdapter):
    provider_name = "polling_provider"

    def __init__(self) -> None:
        self.provider_jobs = ProviderJobRepository()
        self.polled: list[str] = []

    def submit_job(self, submission: ProviderSubmission) -> NormalizedProviderResult:
        raise NotImplementedError("Polling test adapter only supports poll_job.")

    def poll_job(self, provider_job_name: str) -> NormalizedProviderResult:
        self.polled.append(provider_job_name)
        result = NormalizedProviderResult(
            status=ProviderJobStatus.SUCCEEDED.value,
            external_job_id="external-poll-123",
        )
        self.provider_jobs.apply_result(
            provider_job_name,
            result,
            {"code": 200, "data": {"id": "external-poll-123", "status": "completed"}},
        )
        return result

    def cancel_job(self, provider_job_name: str) -> None:
        self.provider_jobs.mark_cancelled(provider_job_name)

    def normalize_result(self, raw_response: Mapping[str, Any]) -> NormalizedProviderResult:
        return NormalizedProviderResult(status=ProviderJobStatus.SUCCEEDED.value)

    def estimate_cost(self, model: str, input_data: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"currency": "USD", "estimated_cost_usd": 0.0, "model": model}


class TestWorkersRealtime(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.local.realtime_log = []

    def test_run_workflow_worker_executes_persisted_run_and_publishes_realtime(self):
        workflow = create_text_workflow(create_project())
        start_result = RunService().start_run(workflow.name)

        run_workflow(start_result.workflow_run)

        workflow_run = frappe.get_doc("AI Workflow Run", start_result.workflow_run)
        node_statuses = {
            row.status
            for row in frappe.get_all(
                "AI Node Run",
                filters={"workflow_run": start_result.workflow_run},
                fields=["status"],
            )
        }
        self.assertEqual(workflow_run.status, "SUCCEEDED")
        self.assertEqual(node_statuses, {"SUCCEEDED"})
        self.assertIn(WORKFLOW_RUN_EVENT, event_names())
        self.assertIn(NODE_RUN_EVENT, event_names())

    def test_run_node_worker_executes_one_node_from_persisted_graph(self):
        workflow = create_text_workflow(create_project())
        start_result = RunService().start_run(workflow.name)
        prompt_node_run = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": start_result.workflow_run, "node_id": "prompt_1"},
            "name",
        )

        run_node(prompt_node_run)

        node_run = frappe.get_doc("AI Node Run", prompt_node_run)
        self.assertEqual(node_run.status, "SUCCEEDED")
        self.assertEqual(json.loads(node_run.output_json), {"text": "Worker text"})
        self.assertIn(NODE_RUN_EVENT, event_names())

    def test_resume_workflow_worker_skips_completed_nodes_and_finishes_run(self):
        workflow = create_text_workflow(create_project())
        start_result = RunService().start_run(workflow.name)
        prompt_node_run = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": start_result.workflow_run, "node_id": "prompt_1"},
            "name",
        )
        run_node(prompt_node_run)

        resume_workflow(start_result.workflow_run)

        workflow_run = frappe.get_doc("AI Workflow Run", start_result.workflow_run)
        output_node_run = frappe.get_doc(
            "AI Node Run",
            frappe.db.get_value(
                "AI Node Run",
                {"workflow_run": start_result.workflow_run, "node_id": "output_1"},
                "name",
            ),
        )
        self.assertEqual(workflow_run.status, "SUCCEEDED")
        self.assertEqual(output_node_run.status, "SUCCEEDED")
        self.assertEqual(json.loads(output_node_run.input_json), {"text": "Worker text"})

    def test_poll_provider_job_worker_updates_provider_job_and_enqueues_resume(self):
        workflow = create_text_workflow(create_project())
        start_result = RunService().start_run(workflow.name)
        node_run_name = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": start_result.workflow_run, "node_id": "prompt_1"},
            "name",
        )
        model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": unique("poll/model"),
                "model_name": "Polling Test Model",
                "provider": "polling_provider",
                "status": "ENABLED",
                "modality": "TEXT_TO_IMAGE",
            }
        )
        provider_job = insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run_name,
                "provider": "polling_provider",
                "model": model.name,
                "external_job_id": "external-poll-123",
                "status": "SUBMITTED",
                "idempotency_key": unique("poll-job"),
                "request_json": json.dumps({"prompt": "Worker text"}),
            }
        )
        registry = ProviderRegistry([PollingProviderAdapter()])

        result = poll_provider_job(provider_job.name, provider_registry=registry)

        provider_job.reload()
        self.assertEqual(result["status"], ProviderJobStatus.SUCCEEDED.value)
        self.assertTrue(result["queue_job_id"].startswith("slow_ai:workflow_run:"))
        self.assertEqual(provider_job.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertIn(PROVIDER_JOB_EVENT, event_names())

    def test_scheduled_provider_polling_polls_only_waiting_external_jobs(self):
        workflow = create_text_workflow(create_project())
        start_result = RunService().start_run(workflow.name)
        node_run_name = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": start_result.workflow_run, "node_id": "prompt_1"},
            "name",
        )
        model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": unique("poll/model"),
                "model_name": "Scheduled Polling Test Model",
                "provider": "polling_provider",
                "status": "ENABLED",
                "modality": "TEXT_TO_IMAGE",
            }
        )
        pollable_job = insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run_name,
                "provider": "polling_provider",
                "model": model.name,
                "external_job_id": "external-poll-123",
                "status": "WAITING_PROVIDER",
                "idempotency_key": unique("scheduled-poll-job"),
                "request_json": json.dumps({"prompt": "Worker text"}),
            }
        )
        queued_job = insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run_name,
                "provider": "polling_provider",
                "model": model.name,
                "status": "QUEUED",
                "idempotency_key": unique("scheduled-queued-job"),
                "request_json": json.dumps({"prompt": "Worker text"}),
            }
        )
        registry = ProviderRegistry([PollingProviderAdapter()])

        result = poll_pending_provider_jobs(provider="polling_provider", provider_registry=registry)

        pollable_job.reload()
        queued_job.reload()
        self.assertEqual([row["provider_job"] for row in result["polled"]], [pollable_job.name])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(result["errors"], [])
        self.assertEqual(pollable_job.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertEqual(queued_job.status, ProviderJobStatus.QUEUED.value)
        self.assertIn(PROVIDER_JOB_EVENT, event_names())

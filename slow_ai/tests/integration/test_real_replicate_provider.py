import json
import os
import time
import unittest
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.billing import create_top_up
from slow_ai.application.models import pricing_summary_from_json
from slow_ai.application.runs import get_history
from slow_ai.application.run_service import RunService
from slow_ai.domain.status import PROVIDER_JOB_TERMINAL_STATUSES, ProviderJobStatus
from slow_ai.providers.contracts import ProviderJobRequest
from slow_ai.providers.replicate.adapter import ReplicateAdapter
from slow_ai.providers.replicate.models import REPLICATE_PROVIDER_NAME, upsert_replicate_model_catalog
from slow_ai.workers.poll_provider_job import poll_provider_job
from slow_ai.workers.resume_workflow import resume_workflow
from slow_ai.workers.run_workflow import run_workflow


REAL_REPLICATE_FLAG = "SLOW_AI_REAL_REPLICATE_TESTS"
REAL_REPLICATE_BUDGET_ENV = "SLOW_AI_REAL_REPLICATE_TEST_BUDGET_USD"
REPLICATE_API_KEY_ENV = "REPLICATE_API_KEY"
DEFAULT_REAL_TEST_BUDGET_USD = Decimal("0.01")
DEFAULT_REPLICATE_TEST_MODEL_ID = "black-forest-labs/flux-schnell"
POLL_TIMEOUT_SECONDS = int(os.environ.get("SLOW_AI_REAL_REPLICATE_POLL_TIMEOUT_SECONDS", "180"))
POLL_INTERVAL_SECONDS = float(os.environ.get("SLOW_AI_REAL_REPLICATE_POLL_INTERVAL_SECONDS", "3"))


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def skip_unless_real_replicate_enabled() -> None:
    if os.environ.get(REAL_REPLICATE_FLAG) != "1":
        raise unittest.SkipTest(f"Set {REAL_REPLICATE_FLAG}=1 to run real Replicate provider tests.")
    if not os.environ.get(REPLICATE_API_KEY_ENV):
        raise unittest.SkipTest(f"Set {REPLICATE_API_KEY_ENV} to run real Replicate provider tests.")


def configured_budget() -> Decimal:
    raw_value = os.environ.get(REAL_REPLICATE_BUDGET_ENV, str(DEFAULT_REAL_TEST_BUDGET_USD))
    try:
        budget = Decimal(str(raw_value))
    except InvalidOperation as exc:
        raise AssertionError(f"{REAL_REPLICATE_BUDGET_ENV} must be a decimal USD value.") from exc
    if budget <= 0:
        raise AssertionError(f"{REAL_REPLICATE_BUDGET_ENV} must be greater than zero.")
    return budget


def select_replicate_model_under_budget() -> tuple:
    upsert_replicate_model_catalog()
    budget = configured_budget()
    model = frappe.get_doc("AI Model", DEFAULT_REPLICATE_TEST_MODEL_ID)
    pricing = pricing_summary_from_json(model.pricing_json)
    if not pricing["pricing_known"]:
        raise AssertionError(
            f"Real Replicate tests refuse to run because {DEFAULT_REPLICATE_TEST_MODEL_ID} "
            "has no known pricing_json."
        )
    price = Decimal(str(pricing["estimated_cost_usd"]))
    if price > budget:
        raise AssertionError(
            f"Real Replicate tests refuse to run: selected model {model.model_id} costs {price} USD, "
            f"which exceeds {REAL_REPLICATE_BUDGET_ENV}={budget}."
        )
    return model, price


def real_test_parameters_for_model(model) -> dict:
    if model.pricing_json:
        pricing = json.loads(model.pricing_json)
        parameters = pricing.get("test_parameters")
        if isinstance(parameters, dict):
            return dict(parameters)
    return {
        "aspect_ratio": "1:1",
        "num_outputs": 1,
        "output_format": "webp",
        "output_quality": 80,
        "num_inference_steps": 4,
    }


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Real Replicate Project"),
            "status": "Open",
        }
    )


def create_provider_account(api_key: str):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": REPLICATE_PROVIDER_NAME,
            "account_label": unique("Real Replicate"),
            "api_key_secret": api_key,
            "is_default": 0,
            "status": "ACTIVE",
            "rate_limit_json": json.dumps({"rpm": 10}),
        }
    )


def create_real_provider_workflow(project, model, provider_account_name: str):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Real Replicate Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {
                        "id": "prompt_1",
                        "type": "text_prompt",
                        "config": {
                            "text": "A small studio product photo of a plain white ceramic cup on a table"
                        },
                    },
                    {
                        "id": "provider_1",
                        "type": "provider_text_to_image",
                        "config": {
                            "provider": REPLICATE_PROVIDER_NAME,
                            "model": model.name,
                            "provider_account": provider_account_name,
                            "parameters": real_test_parameters_for_model(model),
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


def provider_node_run_for(workflow_run: str):
    return frappe.get_doc(
        "AI Node Run",
        frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": workflow_run, "node_id": "provider_1"},
            "name",
        ),
    )


class TestRealReplicateProvider(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        skip_unless_real_replicate_enabled()

    def test_real_replicate_text_to_image_workflow_materializes_history(self):
        model, max_expected_price = select_replicate_model_under_budget()
        provider_account = create_provider_account(os.environ[REPLICATE_API_KEY_ENV])
        project = create_project()
        create_top_up(project.name, str(configured_budget()), "Real Replicate test credit")
        workflow = create_real_provider_workflow(project, model, provider_account.name)

        start_result = RunService().start_run(workflow.name)
        self.assertTrue(frappe.db.exists("AI Workflow Version", start_result.workflow_version))
        self.assertTrue(frappe.db.exists("AI Workflow Run", start_result.workflow_run))
        self.assertEqual(len(start_result.node_runs), 3)

        run_workflow(start_result.workflow_run)
        provider_node_run = provider_node_run_for(start_result.workflow_run)
        provider_job = frappe.get_doc("AI Provider Job", provider_node_run.provider_job)
        self.assertEqual(provider_job.provider, REPLICATE_PROVIDER_NAME)
        self.assertEqual(provider_job.model, model.name)
        self.assertEqual(provider_job.provider_account, provider_account.name)

        deadline = time.time() + POLL_TIMEOUT_SECONDS
        while provider_job.status not in PROVIDER_JOB_TERMINAL_STATUSES:
            if time.time() > deadline:
                raise AssertionError(f"Timed out waiting for Replicate job {provider_job.name}")
            time.sleep(POLL_INTERVAL_SECONDS)
            poll_provider_job(provider_job.name, enqueue_resume=False)
            provider_job.reload()

        if provider_job.status == ProviderJobStatus.SUCCEEDED.value:
            resume_workflow(start_result.workflow_run)

        provider_node_run.reload()
        history = get_history(start_result.workflow_run)
        self.assertEqual(provider_job.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertEqual(provider_node_run.status, "SUCCEEDED")
        self.assertTrue(history["assets"])
        self.assertLessEqual(Decimal(str(provider_job.cost_usd or 0)), max_expected_price)

    def test_real_replicate_invalid_api_key_persists_failed_provider_job(self):
        model, _ = select_replicate_model_under_budget()
        provider_account = create_provider_account("invalid-replicate-api-key")
        idempotency_key = unique("real-replicate-invalid-key")

        result = ReplicateAdapter().create_and_submit_job(
            ProviderJobRequest(
                provider=REPLICATE_PROVIDER_NAME,
                model=model.name,
                provider_account_name=provider_account.name,
                idempotency_key=idempotency_key,
                input_data={"prompt": "A small product photo"},
            )
        )

        provider_job = frappe.get_doc(
            "AI Provider Job",
            frappe.db.get_value("AI Provider Job", {"idempotency_key": idempotency_key}, "name"),
        )
        self.assertEqual(result.status, ProviderJobStatus.FAILED.value)
        self.assertEqual(provider_job.status, ProviderJobStatus.FAILED.value)
        self.assertTrue(provider_job.raw_error_json)
        self.assertFalse(frappe.db.exists("AI Asset", {"source_provider_job": provider_job.name}))
        self.assertFalse(frappe.db.exists("AI Credit Ledger", {"provider_job": provider_job.name}))

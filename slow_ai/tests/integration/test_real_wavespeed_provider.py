import json
import os
import time
import unittest
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.runs import get_history
from slow_ai.application.run_service import RunService
from slow_ai.domain.status import PROVIDER_JOB_TERMINAL_STATUSES, ProviderJobStatus
from slow_ai.providers.contracts import ProviderJobRequest
from slow_ai.providers.wavespeed.adapter import WaveSpeedAdapter
from slow_ai.workers.poll_provider_job import poll_provider_job
from slow_ai.workers.resume_workflow import resume_workflow
from slow_ai.workers.run_workflow import run_workflow


REAL_PROVIDER_FLAG = "SLOW_AI_REAL_PROVIDER_TESTS"
REAL_PROVIDER_BUDGET_ENV = "SLOW_AI_REAL_PROVIDER_TEST_BUDGET_USD"
WAVESPEED_API_KEY_ENV = "WAVESPEED_API_KEY"
DEFAULT_REAL_TEST_BUDGET_USD = Decimal("0.02")
DEFAULT_WAVESPEED_TEST_MODEL_ID = "wavespeed-ai/flux-dev"
DEFAULT_WAVESPEED_TEST_MODEL_PRICE_USD = Decimal("0.012")
POLL_TIMEOUT_SECONDS = int(os.environ.get("SLOW_AI_REAL_PROVIDER_POLL_TIMEOUT_SECONDS", "180"))
POLL_INTERVAL_SECONDS = float(os.environ.get("SLOW_AI_REAL_PROVIDER_POLL_INTERVAL_SECONDS", "3"))


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def real_provider_enabled() -> bool:
    return os.environ.get(REAL_PROVIDER_FLAG) == "1" and bool(os.environ.get(WAVESPEED_API_KEY_ENV))


def skip_unless_real_provider_enabled() -> None:
    if os.environ.get(REAL_PROVIDER_FLAG) != "1":
        raise unittest.SkipTest(f"Set {REAL_PROVIDER_FLAG}=1 to run real WaveSpeed provider tests.")
    if not os.environ.get(WAVESPEED_API_KEY_ENV):
        raise unittest.SkipTest(f"Set {WAVESPEED_API_KEY_ENV} to run real WaveSpeed provider tests.")


def configured_budget() -> Decimal:
    raw_value = os.environ.get(REAL_PROVIDER_BUDGET_ENV, str(DEFAULT_REAL_TEST_BUDGET_USD))
    try:
        budget = Decimal(str(raw_value))
    except InvalidOperation as exc:
        raise AssertionError(f"{REAL_PROVIDER_BUDGET_ENV} must be a decimal USD value.") from exc
    if budget <= 0:
        raise AssertionError(f"{REAL_PROVIDER_BUDGET_ENV} must be greater than zero.")
    return budget


def ensure_default_wavespeed_test_model() -> str:
    pricing = {
        "unit": "run",
        "amount_usd": str(DEFAULT_WAVESPEED_TEST_MODEL_PRICE_USD),
        "source": "wavespeed_model_card",
        "test_parameters": real_test_parameters(),
    }
    if frappe.db.exists("AI Model", DEFAULT_WAVESPEED_TEST_MODEL_ID):
        return DEFAULT_WAVESPEED_TEST_MODEL_ID
    return insert_doc(
        {
            "doctype": "AI Model",
            "model_id": DEFAULT_WAVESPEED_TEST_MODEL_ID,
            "model_name": "WaveSpeed Flux Dev Real Provider Test",
            "provider": "wavespeed",
            "status": "ENABLED",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps(pricing),
        }
    ).name


def select_cheapest_wavespeed_model_under_budget() -> tuple:
    ensure_default_wavespeed_test_model()
    budget = configured_budget()
    rows = frappe.get_all(
        "AI Model",
        filters={"provider": "wavespeed", "status": "ENABLED", "modality": "TEXT_TO_IMAGE"},
        fields=["name", "model_id", "model_name", "pricing_json"],
        order_by="creation asc",
    )
    priced_rows = []
    unpriced_rows = []
    for row in rows:
        price = price_from_pricing_json(row.pricing_json)
        if price is None:
            unpriced_rows.append(row.model_id)
            continue
        priced_rows.append((price, row))

    if not priced_rows:
        raise AssertionError(
            "Real WaveSpeed tests refuse to run because no enabled WaveSpeed TEXT_TO_IMAGE "
            "AI Model has known pricing_json."
        )

    price, row = sorted(priced_rows, key=lambda item: (item[0], item[1].model_id))[0]
    if price > budget:
        raise AssertionError(
            f"Real WaveSpeed tests refuse to run: selected model {row.model_id} costs {price} USD, "
            f"which exceeds {REAL_PROVIDER_BUDGET_ENV}={budget}."
        )
    return row, price


def price_from_pricing_json(pricing_json: str | None) -> Decimal | None:
    if not pricing_json:
        return None
    pricing = json.loads(pricing_json)
    for key in ("test_cost_usd", "amount_usd", "base_price", "price_usd"):
        value = pricing.get(key)
        if value in (None, ""):
            continue
        price = Decimal(str(value))
        if price <= 0:
            return None
        return price
    return None


def real_test_parameters_for_model(model) -> dict:
    if model.pricing_json:
        pricing = json.loads(model.pricing_json)
        parameters = pricing.get("test_parameters")
        if isinstance(parameters, dict):
            return dict(parameters)
    return real_test_parameters()


def real_test_parameters() -> dict:
    return {
        "size": "1024*1024",
        "num_images": 1,
        "output_format": "jpeg",
        "enable_base64_output": False,
        "enable_sync_mode": False,
    }


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Real WaveSpeed Project"),
            "status": "Open",
        }
    )


def create_provider_account(api_key: str, *, is_default: int = 0):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": "wavespeed",
            "account_label": unique("Real WaveSpeed"),
            "api_key_secret": api_key,
            "is_default": is_default,
            "status": "ACTIVE",
            "rate_limit_json": json.dumps({"rpm": 10}),
        }
    )


def create_real_provider_workflow(project, model, provider_account_name: str):
    parameters = real_test_parameters_for_model(model)
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Real WaveSpeed Workflow"),
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
                            "provider": "wavespeed",
                            "model": model.name,
                            "provider_account": provider_account_name,
                            "parameters": parameters,
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


class TestRealWaveSpeedProvider(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        skip_unless_real_provider_enabled()

    def test_real_wavespeed_text_to_image_workflow_materializes_history(self):
        model_row, max_expected_price = select_cheapest_wavespeed_model_under_budget()
        model = frappe.get_doc("AI Model", model_row.name)
        provider_account = create_provider_account(os.environ[WAVESPEED_API_KEY_ENV])
        project = create_project()
        workflow = create_real_provider_workflow(project, model, provider_account.name)

        start_result = RunService().start_run(workflow.name)
        self.assertTrue(frappe.db.exists("AI Workflow Version", start_result.workflow_version))
        self.assertTrue(frappe.db.exists("AI Workflow Run", start_result.workflow_run))
        self.assertEqual(len(start_result.node_runs), 3)
        self.assertEqual(frappe.get_doc("AI Workflow Run", start_result.workflow_run).status, "QUEUED")

        run_workflow(start_result.workflow_run)
        provider_node_run = provider_node_run_for(start_result.workflow_run)
        self.assertTrue(provider_node_run.provider_job)
        provider_job = frappe.get_doc("AI Provider Job", provider_node_run.provider_job)
        self.assertEqual(provider_job.provider, "wavespeed")
        self.assertEqual(provider_job.model, model.name)
        self.assertEqual(provider_job.provider_account, provider_account.name)
        self.assertTrue(provider_job.request_json)
        self.assertTrue(provider_job.submitted_at)

        terminal_status = self.poll_until_terminal(provider_job.name)
        self.assertEqual(terminal_status, ProviderJobStatus.SUCCEEDED.value)
        resume_workflow(start_result.workflow_run)

        provider_node_run.reload()
        provider_job.reload()
        workflow_run = frappe.get_doc("AI Workflow Run", start_result.workflow_run)
        self.assertEqual(workflow_run.status, "SUCCEEDED")
        self.assertEqual(provider_node_run.status, "SUCCEEDED")
        self.assertEqual(provider_job.status, ProviderJobStatus.SUCCEEDED.value)
        self.assertLessEqual(max_expected_price, configured_budget())

        assets = frappe.get_all(
            "AI Asset",
            filters={"source_provider_job": provider_job.name},
            fields=["name", "asset_type", "url", "mime_type", "source_workflow_run", "source_node_run"],
        )
        self.assertGreaterEqual(len(assets), 1)
        self.assertEqual(assets[0].asset_type, "IMAGE")
        self.assertEqual(assets[0].source_workflow_run, start_result.workflow_run)
        self.assertEqual(assets[0].source_node_run, provider_node_run.name)
        self.assertTrue(assets[0].url)

        ledger = frappe.get_all(
            "AI Credit Ledger",
            filters={"provider_job": provider_job.name, "ledger_type": "DEBIT"},
            fields=["name", "amount_usd", "provider_job"],
        )
        if float(provider_job.cost_usd or 0) > 0:
            self.assertEqual(len(ledger), 1)
            self.assertEqual(float(ledger[0].amount_usd), float(provider_job.cost_usd))

        history = get_history(start_result.workflow_run)
        self.assertIn(provider_job.name, {row["name"] for row in history["provider_jobs"]})
        self.assertIn(assets[0].name, {row["name"] for row in history["assets"]})
        if ledger:
            self.assertIn(ledger[0].name, {row["name"] for row in history["ledger"]})

    def test_real_wavespeed_invalid_api_key_persists_failed_provider_job(self):
        model_row, _ = select_cheapest_wavespeed_model_under_budget()
        provider_account = create_provider_account("invalid-wavespeed-api-key")
        idempotency_key = unique("real-wavespeed-invalid-key")

        result = WaveSpeedAdapter().create_and_submit_job(
            ProviderJobRequest(
                provider="wavespeed",
                model=model_row.name,
                input_data={"prompt": "This request should fail before generation."},
                provider_account_name=provider_account.name,
                idempotency_key=idempotency_key,
            )
        )

        provider_job_name = frappe.db.get_value(
            "AI Provider Job",
            {"idempotency_key": idempotency_key},
            "name",
        )
        provider_job = frappe.get_doc("AI Provider Job", provider_job_name)
        self.assertEqual(result.status, ProviderJobStatus.FAILED.value)
        self.assertEqual(provider_job.status, ProviderJobStatus.FAILED.value)
        self.assertTrue(provider_job.request_json)
        self.assertTrue(provider_job.response_json)
        self.assertTrue(provider_job.raw_error_json)
        self.assertFalse(frappe.db.exists("AI Asset", {"source_provider_job": provider_job.name}))
        self.assertFalse(frappe.db.exists("AI Credit Ledger", {"provider_job": provider_job.name}))

    def poll_until_terminal(self, provider_job_name: str) -> str:
        deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            provider_job = frappe.get_doc("AI Provider Job", provider_job_name)
            status = ProviderJobStatus(provider_job.status)
            if status in PROVIDER_JOB_TERMINAL_STATUSES:
                return status.value
            poll_provider_job(provider_job_name, enqueue_resume=False)
            time.sleep(POLL_INTERVAL_SECONDS)
        provider_job = frappe.get_doc("AI Provider Job", provider_job_name)
        raise AssertionError(
            f"WaveSpeed provider job did not reach terminal state within {POLL_TIMEOUT_SECONDS}s: "
            f"{provider_job.name} {provider_job.status}"
        )

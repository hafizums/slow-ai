import json
from contextlib import contextmanager
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.domain.exceptions import RunPreflightError


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Preflight Project"),
            "status": "Open",
        }
    )


def create_model(
    *,
    provider: str,
    status: str = "ENABLED",
    pricing_json=None,
):
    values = {
        "doctype": "AI Model",
        "model_id": unique(f"{provider}/model"),
        "model_name": "Preflight Test Model",
        "provider": provider,
        "status": status,
        "modality": "TEXT_TO_IMAGE",
    }
    if pricing_json is not None:
        values["pricing_json"] = json.dumps(pricing_json)
    return insert_doc(values)


def create_provider_account(*, provider: str, status: str = "ACTIVE", is_default: int = 1):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("Preflight Provider"),
            "api_key_secret": "preflight-test-key",
            "is_default": is_default,
            "status": status,
        }
    )


def create_text_workflow(project):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Preflight Text Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Preflight text"}},
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
            "layout_json": "{}",
        }
    )


def create_provider_workflow(project, *, provider: str, model_name: str, provider_account: str | None = None):
    config = {
        "provider": provider,
        "model": model_name,
        "parameters": {"size": "1024*1024"},
    }
    if provider_account:
        config["provider_account"] = provider_account
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Preflight Provider Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Preflight prompt"}},
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


@contextmanager
def preflight_policy(**values):
    old_values = {key: frappe.conf.get(key) for key in values}
    for key, value in values.items():
        frappe.conf[key] = value
    try:
        yield
    finally:
        for key, value in old_values.items():
            if value is None:
                frappe.conf.pop(key, None)
            else:
                frappe.conf[key] = value


class TestRunPreflight(FrappeTestCase):
    def test_non_provider_workflow_still_starts(self):
        workflow = create_text_workflow(create_project())

        with preflight_policy(
            slow_ai_run_preflight_require_known_pricing=True,
            slow_ai_run_preflight_max_cost_usd="0",
        ):
            result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertTrue(frappe.db.exists("AI Workflow Run", result["workflow_run"]))
        self.assertTrue(result["queue_job_id"].startswith("slow_ai:workflow_run:"))

    def test_provider_workflow_with_enabled_model_account_and_budget_starts(self):
        provider = unique("allowed-provider")
        model = create_model(
            provider=provider,
            pricing_json={"unit": "run", "amount_usd": "0.10"},
        )
        create_provider_account(provider=provider)
        workflow = create_provider_workflow(create_project(), provider=provider, model_name=model.name)

        with preflight_policy(slow_ai_run_preflight_max_cost_usd="0.20"):
            result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertTrue(frappe.db.exists("AI Workflow Version", result["workflow_version"]))
        self.assertTrue(frappe.db.exists("AI Workflow Run", result["workflow_run"]))
        self.assertEqual(len(result["node_runs"]), 3)

    def test_disabled_model_is_rejected_before_enqueue(self):
        provider = unique("disabled-provider")
        model = create_model(
            provider=provider,
            status="DISABLED",
            pricing_json={"unit": "run", "amount_usd": "0.10"},
        )
        create_provider_account(provider=provider)
        workflow = create_provider_workflow(create_project(), provider=provider, model_name=model.name)

        self.assert_preflight_rejects_without_side_effects(workflow, "disabled model")

    def test_missing_provider_account_is_rejected_before_enqueue(self):
        provider = unique("missing-account-provider")
        model = create_model(
            provider=provider,
            pricing_json={"unit": "run", "amount_usd": "0.10"},
        )
        workflow = create_provider_workflow(create_project(), provider=provider, model_name=model.name)

        self.assert_preflight_rejects_without_side_effects(workflow, "No active default provider account")

    def test_inactive_provider_account_is_rejected_before_enqueue(self):
        provider = unique("inactive-account-provider")
        model = create_model(
            provider=provider,
            pricing_json={"unit": "run", "amount_usd": "0.10"},
        )
        create_provider_account(provider=provider, status="DISABLED")
        workflow = create_provider_workflow(create_project(), provider=provider, model_name=model.name)

        self.assert_preflight_rejects_without_side_effects(workflow, "No active default provider account")

    def test_missing_pricing_is_rejected_when_strict_policy_enabled(self):
        provider = unique("unpriced-provider")
        model = create_model(provider=provider)
        create_provider_account(provider=provider)
        workflow = create_provider_workflow(create_project(), provider=provider, model_name=model.name)

        with preflight_policy(slow_ai_run_preflight_require_known_pricing=True):
            self.assert_preflight_rejects_without_side_effects(workflow, "without known pricing")

    def test_over_budget_provider_workflow_is_rejected_before_enqueue(self):
        provider = unique("over-budget-provider")
        model = create_model(
            provider=provider,
            pricing_json={"unit": "run", "amount_usd": "0.25"},
        )
        create_provider_account(provider=provider)
        workflow = create_provider_workflow(create_project(), provider=provider, model_name=model.name)

        with preflight_policy(slow_ai_run_preflight_max_cost_usd="0.10"):
            self.assert_preflight_rejects_without_side_effects(workflow, "exceeds configured budget")

    def test_missing_pricing_can_start_when_strict_policy_is_disabled(self):
        provider = unique("unpriced-allowed-provider")
        model = create_model(provider=provider)
        create_provider_account(provider=provider)
        workflow = create_provider_workflow(create_project(), provider=provider, model_name=model.name)

        with preflight_policy(slow_ai_run_preflight_require_known_pricing=False):
            result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertTrue(frappe.db.exists("AI Workflow Run", result["workflow_run"]))

    def assert_preflight_rejects_without_side_effects(self, workflow, message: str) -> None:
        provider_job_count = frappe.db.count("AI Provider Job")
        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertIn(message, str(exc.exception))
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)
        self.assertFalse(frappe.db.exists("AI Workflow Version", {"workflow": workflow.name}))
        self.assertFalse(frappe.db.exists("AI Workflow Run", {"workflow": workflow.name}))

import json
from contextlib import contextmanager
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.domain.exceptions import RunPreflightError
from slow_ai.providers.wavespeed.models import upsert_wavespeed_model_catalog


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Model Catalog Project"),
            "status": "Open",
        }
    )


def create_provider_account(*, provider: str, status: str = "ACTIVE", is_default: int = 1):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("Model Catalog Account"),
            "api_key_secret": "model-catalog-test-key",
            "is_default": is_default,
            "status": status,
        }
    )


def create_model(
    *,
    provider: str,
    status: str = "ENABLED",
    pricing_json=None,
    node_type: str = "provider_text_to_image",
    category: str = "provider",
):
    values = {
        "doctype": "AI Model",
        "model_id": unique(f"{provider}/model"),
        "model_slug": unique(f"{provider}-slug"),
        "model_name": "Model Catalog Test Model",
        "provider": provider,
        "status": status,
        "modality": "TEXT_TO_IMAGE",
        "node_type": node_type,
        "category": category,
        "capabilities_json": json.dumps({"text_to_image": True}),
        "input_metadata_json": json.dumps({"prompt": "text"}),
        "output_metadata_json": json.dumps({"image": "AI Asset"}),
    }
    if pricing_json is not None:
        values["pricing_json"] = json.dumps(pricing_json)
    return insert_doc(values)


def create_provider_workflow(project, *, provider: str, model_ref: str):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Model Catalog Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Catalog prompt"}},
                    {
                        "id": "provider_1",
                        "type": "provider_text_to_image",
                        "config": {
                            "provider": provider,
                            "model": model_ref,
                            "parameters": {"size": "1024*1024"},
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


class TestModelCatalogAdmin(FrappeTestCase):
    def test_model_record_validates_json_and_public_metadata_is_safe(self):
        model = create_model(
            provider=unique("safe-provider"),
            pricing_json={"unit": "run", "amount_usd": "0.034", "currency": "USD"},
        )

        metadata = frappe.call(
            "slow_ai.api.models.get_model_metadata",
            model_ids=json.dumps([model.name, model.model_id, model.model_slug]),
        )
        by_slug = metadata["models"][model.model_slug]
        detail = frappe.call("slow_ai.api.models.get_model", model=model.model_slug)["model"]

        self.assertEqual(by_slug["name"], model.name)
        self.assertEqual(by_slug["node_type"], "provider_text_to_image")
        self.assertEqual(by_slug["category"], "provider")
        self.assertEqual(by_slug["estimated_cost_usd"], "0.034")
        self.assertEqual(by_slug["capabilities"]["text_to_image"], True)
        self.assertEqual(detail["model_id"], model.model_id)
        self.assertNotIn("pricing_json", by_slug)
        self.assertNotIn("api_key_secret", by_slug)

        invalid_model = create_model(
            provider=unique("invalid-json-provider"),
            pricing_json={"unit": "run", "amount_usd": "0.01"},
        )
        invalid_model.capabilities_json = "[]"
        with self.assertRaises(frappe.ValidationError):
            invalid_model.save(ignore_permissions=True)

    def test_disabled_models_are_hidden_from_default_list_and_rejected_by_preflight(self):
        provider = unique("disabled-catalog-provider")
        model = create_model(
            provider=provider,
            status="DISABLED",
            pricing_json={"unit": "run", "amount_usd": "0.10"},
        )
        create_provider_account(provider=provider)
        workflow = create_provider_workflow(create_project(), provider=provider, model_ref=model.name)

        listed = frappe.call("slow_ai.api.models.list_models", provider=provider)

        self.assertNotIn(model.name, {row["name"] for row in listed["models"]})
        self.assert_preflight_rejects_without_provider_job(workflow, "disabled model")

    def test_pricing_parser_is_shared_by_metadata_and_preflight_budget(self):
        provider = unique("budget-catalog-provider")
        model = create_model(
            provider=provider,
            pricing_json={"unit": "run", "base_price": "0.25", "currency": "USD"},
        )
        create_provider_account(provider=provider)
        workflow = create_provider_workflow(create_project(), provider=provider, model_ref=model.model_id)
        metadata = frappe.call("slow_ai.api.models.get_model_metadata", model_ids=json.dumps([model.model_id]))

        self.assertEqual(metadata["models"][model.model_id]["estimated_cost_usd"], "0.25")
        with preflight_policy(slow_ai_run_preflight_max_cost_usd="0.10"):
            self.assert_preflight_rejects_without_provider_job(workflow, "exceeds configured budget")

    def test_provider_node_rejects_mismatched_model_metadata(self):
        provider = unique("mismatch-catalog-provider")
        model = create_model(
            provider=provider,
            pricing_json={"unit": "run", "amount_usd": "0.01"},
            node_type="provider_text_to_video",
        )
        create_provider_account(provider=provider)
        workflow = create_provider_workflow(create_project(), provider=provider, model_ref=model.name)

        self.assert_preflight_rejects_without_provider_job(workflow, "not provider_text_to_image")

    def test_model_slug_resolves_for_provider_run_preflight(self):
        provider = unique("slug-catalog-provider")
        model = create_model(
            provider=provider,
            pricing_json={"unit": "run", "amount_usd": "0.01"},
        )
        create_provider_account(provider=provider)
        workflow = create_provider_workflow(create_project(), provider=provider, model_ref=model.model_slug)
        provider_job_count = frappe.db.count("AI Provider Job")

        result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertTrue(frappe.db.exists("AI Workflow Run", result["workflow_run"]))
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)

    def test_wavespeed_seed_upserts_catalog_without_provider_calls(self):
        provider_job_count = frappe.db.count("AI Provider Job")

        names = upsert_wavespeed_model_catalog()

        self.assertIn("wavespeed-ai/flux-dev", names)
        z_image = frappe.get_doc("AI Model", "wavespeed-ai/z-image/turbo")
        self.assertEqual(z_image.status, "DISABLED")
        self.assertEqual(z_image.node_type, "provider_text_to_image")
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)

    def assert_preflight_rejects_without_provider_job(self, workflow, message: str) -> None:
        provider_job_count = frappe.db.count("AI Provider Job")
        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertIn(message, str(exc.exception))
        self.assertEqual(frappe.db.count("AI Provider Job"), provider_job_count)
        self.assertFalse(frappe.db.exists("AI Workflow Version", {"workflow": workflow.name}))
        self.assertFalse(frappe.db.exists("AI Workflow Run", {"workflow": workflow.name}))

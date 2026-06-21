import json
from contextlib import contextmanager
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.billing import create_top_up
from slow_ai.domain.exceptions import RunPreflightError
from slow_ai.tests.integration.test_model_catalog_admin import create_model
from slow_ai.tests.integration.test_model_catalog_admin import create_project
from slow_ai.tests.integration.test_model_catalog_admin import create_provider_account
from slow_ai.tests.integration.test_model_catalog_admin import create_provider_workflow
from slow_ai.tests.integration.test_project_membership import ensure_user
from slow_ai.tests.integration.test_public_tool_page import add_member


SIDE_EFFECT_DOCTYPES = (
    "AI Provider Account",
    "AI Workflow",
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
)

MODEL_FIELDS = (
    "name",
    "status",
    "pricing_json",
    "capabilities_json",
    "input_metadata_json",
    "output_metadata_json",
    "modified",
)

UNSAFE_FRAGMENTS = (
    "MODEL_ACCESS_SECRET",
    "model-access-provider-account",
    "https://provider.example.invalid",
    "api_key",
    "api_key_secret",
    "Authorization",
    "Bearer",
    "provider_account",
    "request_json",
    "response_json",
    "raw_error_json",
    "draft_nodes_json",
    "draft_edges_json",
    "layout_json",
)


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def model_snapshot() -> list[dict]:
    rows = frappe.get_all("AI Model", fields=list(MODEL_FIELDS), order_by="name asc")
    return json.loads(json.dumps([dict(row) for row in rows], default=str))


def assert_safe_payload(testcase: FrappeTestCase, payload) -> None:
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


def assert_no_side_effects(testcase: FrappeTestCase, before_counts: dict[str, int], before_models: list[dict]) -> None:
    testcase.assertEqual(counts(), before_counts)
    testcase.assertEqual(model_snapshot(), before_models)


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


class TestModelCatalogAccessMatrix(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"model-access-owner-{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"model-access-editor-{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"model-access-viewer-{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"model-access-billing-{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"model-access-outsider-{uuid4().hex[:8]}@example.test")
        self.project = create_project()
        frappe.db.set_value("AI Project", self.project.name, "owner", self.owner)
        self.project.reload()
        add_member(self.project.name, self.editor, "EDITOR")
        add_member(self.project.name, self.viewer, "VIEWER")
        add_member(self.project.name, self.billing, "BILLING")

    def tearDown(self):
        frappe.set_user("Administrator")

    def _create_safe_model(self):
        return create_model(
            provider=unique("model-access-provider"),
            pricing_json={"unit": "run", "amount_usd": "0.025", "currency": "USD"},
        )

    def test_safe_model_reads_are_available_to_roles_and_are_side_effect_free(self):
        model = self._create_safe_model()
        model.capabilities_json = json.dumps(
            {
                "text_to_image": True,
                "api_key": "MODEL_ACCESS_SECRET",
                "notes": "Docs at https://provider.example.invalid/private Authorization: Bearer MODEL_ACCESS_SECRET",
            }
        )
        model.input_metadata_json = json.dumps({"prompt": "text", "provider_account": "model-access-provider-account"})
        model.output_metadata_json = json.dumps({"image": "AI Asset", "raw_error_json": {"token": "MODEL_ACCESS_SECRET"}})
        model.save(ignore_permissions=True)

        before_counts = counts()
        before_models = model_snapshot()

        for user in (self.owner, self.editor, self.viewer, self.billing, self.outsider, "Guest", "Administrator"):
            frappe.set_user(user)
            metadata = frappe.call("slow_ai.api.models.get_model_metadata", model_ids=json.dumps([model.model_slug]))
            listed = frappe.call("slow_ai.api.models.list_models", provider=model.provider, status="ALL")
            detail = frappe.call("slow_ai.api.models.get_model", model=model.model_id)

            self.assertEqual(metadata["models"][model.model_slug]["name"], model.name)
            self.assertIn(model.name, {row["name"] for row in listed["models"]})
            self.assertEqual(detail["model"]["name"], model.name)
            self.assertTrue(detail["model"]["capabilities"]["text_to_image"])
            assert_safe_payload(self, {"metadata": metadata, "listed": listed, "detail": detail})

        frappe.set_user("Administrator")
        assert_no_side_effects(self, before_counts, before_models)

    def test_model_admin_mutations_are_system_manager_only_and_safe(self):
        model = self._create_safe_model()

        before_counts = counts()
        before_models = model_snapshot()
        for user in (self.owner, self.editor, self.viewer, self.billing, self.outsider, "Guest"):
            frappe.set_user(user)
            for method, kwargs in (
                ("slow_ai.api.models.update_model_status", {"model": model.name, "status": "DISABLED"}),
                ("slow_ai.api.models.update_model_pricing", {"model": model.name, "amount_usd": "0.011"}),
                (
                    "slow_ai.api.models.update_model_metadata",
                    {"model": model.name, "capabilities": json.dumps({"safe": True})},
                ),
            ):
                with self.assertRaises(frappe.PermissionError, msg=f"{user} unexpectedly called {method}"):
                    frappe.call(method, **kwargs)

        frappe.set_user("Administrator")
        assert_no_side_effects(self, before_counts, before_models)

        non_model_counts = counts()
        disabled = frappe.call("slow_ai.api.models.update_model_status", model=model.name, status="DISABLED")
        priced = frappe.call(
            "slow_ai.api.models.update_model_pricing",
            model=model.name,
            amount_usd="0.019",
            unit="run",
            currency="USD",
        )
        metadata = frappe.call(
            "slow_ai.api.models.update_model_metadata",
            model=model.name,
            capabilities=json.dumps({"safe": True, "api_key": "MODEL_ACCESS_SECRET"}),
            input_metadata=json.dumps({"prompt": "text"}),
            output_metadata=json.dumps({"image": "AI Asset"}),
        )

        self.assertEqual(disabled["model"]["status"], "DISABLED")
        self.assertEqual(priced["model"]["estimated_cost_usd"], "0.019")
        self.assertTrue(metadata["model"]["capabilities"]["safe"])
        assert_safe_payload(self, {"disabled": disabled, "priced": priced, "metadata": metadata})
        self.assertEqual(counts(), non_model_counts)

    def test_model_preflight_guards_reject_before_execution_side_effects(self):
        provider = unique("model-preflight-provider")
        create_provider_account(provider=provider)
        disabled = create_model(
            provider=provider,
            status="DISABLED",
            pricing_json={"unit": "run", "amount_usd": "0.01"},
        )
        unpriced = create_model(provider=provider, pricing_json=None)
        mismatched = create_model(
            provider=provider,
            pricing_json={"unit": "run", "amount_usd": "0.01"},
            node_type="provider_text_to_video",
        )

        for model_ref, expected in (
            (disabled.name, "disabled model"),
            (unpriced.name, "without known pricing"),
            (mismatched.name, "not provider_text_to_image"),
        ):
            workflow = create_provider_workflow(self.project, provider=provider, model_ref=model_ref)
            before_counts = counts()
            before_models = model_snapshot()
            with preflight_policy(slow_ai_run_preflight_require_known_pricing=True):
                with self.assertRaises(RunPreflightError) as exc:
                    frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)
            self.assertIn(expected, str(exc.exception))
            self.assertEqual(frappe.db.count("AI Workflow Version", {"workflow": workflow.name}), 0)
            self.assertEqual(frappe.db.count("AI Workflow Run", {"workflow": workflow.name}), 0)
            assert_no_side_effects(self, before_counts, before_models)

    def test_enabled_priced_model_with_balance_passes_preflight_without_provider_call(self):
        provider = unique("model-allowed-provider")
        create_provider_account(provider=provider)
        model = create_model(
            provider=provider,
            pricing_json={"unit": "run", "amount_usd": "0.01", "currency": "USD"},
        )
        create_top_up(self.project.name, "0.05", "Model access matrix credit")
        workflow = create_provider_workflow(self.project, provider=provider, model_ref=model.model_slug)
        before_provider_jobs = frappe.db.count("AI Provider Job")

        frappe.set_user(self.owner)
        result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertTrue(result["workflow_run"])
        self.assertTrue(result["workflow_version"])
        self.assertEqual(frappe.db.count("AI Provider Job"), before_provider_jobs)

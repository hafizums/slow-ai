import json
from contextlib import contextmanager
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.billing import create_top_up
from slow_ai.domain.exceptions import RunPreflightError


SIDE_EFFECT_DOCTYPES = (
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
)

UNSAFE_ERROR_FRAGMENTS = (
    "compat-secret",
    "compat-account-label",
    "api_key",
    "Authorization",
    "Bearer",
    "request_json",
    "response_json",
    "raw_error_json",
    "Traceback",
    "draft_nodes_json",
    "draft_edges_json",
    "layout_json",
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


def assert_safe_error(testcase: FrappeTestCase, error: Exception, *extra_forbidden: str) -> None:
    text = str(error)
    for fragment in UNSAFE_ERROR_FRAGMENTS + tuple(extra_forbidden):
        testcase.assertNotIn(fragment, text, fragment)


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


def create_project(prefix: str = "Compatibility Project"):
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique(prefix),
            "status": "Open",
        }
    )


def create_model(
    provider: str,
    *,
    status: str = "ENABLED",
    node_type: str = "provider_text_to_image",
    pricing_json=None,
):
    values = {
        "doctype": "AI Model",
        "model_id": unique(f"{provider}/model"),
        "model_slug": unique(f"{provider}-model"),
        "model_name": unique("Compatibility Model"),
        "provider": provider,
        "status": status,
        "category": "provider",
        "node_type": node_type,
        "modality": "TEXT_TO_IMAGE" if node_type != "provider_text_to_speech" else "TEXT_TO_SPEECH",
        "capabilities_json": json.dumps({"node_type": node_type}),
        "input_metadata_json": json.dumps({"prompt": "text"}),
        "output_metadata_json": json.dumps({"asset": "AI Asset"}),
    }
    if pricing_json is not None:
        values["pricing_json"] = json.dumps(pricing_json)
    return insert_doc(values)


def create_provider_account(
    provider: str,
    *,
    status: str = "ACTIVE",
    is_default: int = 1,
    project: str | None = None,
    user: str | None = None,
):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("compat-account-label"),
            "api_key_secret": "compat-secret",
            "is_default": is_default,
            "status": status,
            "project": project,
            "user": user,
        }
    )


def create_text_to_image_workflow(
    project,
    *,
    provider: str,
    model_ref: str,
    provider_account: str | None = None,
):
    config = {"provider": provider, "model": model_ref, "parameters": {"size": "1024x1024"}}
    if provider_account:
        config["provider_account"] = provider_account
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Compatibility Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Compatibility prompt"}},
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


def create_text_to_speech_workflow(project, *, provider: str, model_ref: str):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Compatibility TTS Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {
                        "id": "tts_1",
                        "type": "provider_text_to_speech",
                        "config": {"provider": provider, "model": model_ref, "text": "Read this text"},
                    },
                    {"id": "output_1", "type": "export_output", "config": {}},
                ]
            ),
            "draft_edges_json": json.dumps(
                [
                    {
                        "id": "edge_1",
                        "source": "tts_1",
                        "source_port": "audio",
                        "target": "output_1",
                        "target_port": "audio",
                    }
                ]
            ),
            "layout_json": "{}",
        }
    )


class TestProviderModelCompatibilityMatrix(FrappeTestCase):
    def tearDown(self):
        frappe.set_user("Administrator")

    def test_valid_text_to_image_combination_starts_with_reservation_but_no_provider_job(self):
        provider = unique("compat-valid-provider")
        project = create_project()
        model = create_model(provider, pricing_json={"unit": "run", "amount_usd": "0.05"})
        create_provider_account(provider, project=project.name)
        create_top_up(project.name, "0.20", "Compatibility valid credit")
        workflow = create_text_to_image_workflow(project, provider=provider, model_ref=model.model_slug)

        before = counts()
        result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertTrue(result["queue_job_id"].startswith("slow_ai:workflow_run:"))
        self.assertTrue(frappe.db.exists("AI Workflow Version", result["workflow_version"]))
        self.assertTrue(frappe.db.exists("AI Workflow Run", result["workflow_run"]))
        self.assertEqual(len(result["node_runs"]), 3)
        self.assertEqual(frappe.db.count("AI Provider Job", {"node_run": ["in", result["node_runs"]]}), 0)
        self.assertEqual(
            frappe.db.count("AI Credit Ledger", {"workflow_run": result["workflow_run"], "ledger_type": "RESERVE"}),
            1,
        )
        assert_count_delta(
            self,
            before,
            {
                "AI Workflow Version": 1,
                "AI Workflow Run": 1,
                "AI Node Run": 3,
                "AI Credit Ledger": 1,
            },
        )

    def test_valid_second_provider_node_type_combination_starts_without_provider_job_before_worker(self):
        provider = unique("compat-tts-provider")
        project = create_project()
        model = create_model(
            provider,
            node_type="provider_text_to_speech",
            pricing_json={"unit": "run", "amount_usd": "0.03"},
        )
        create_provider_account(provider, project=project.name)
        create_top_up(project.name, "0.20", "Compatibility TTS credit")
        workflow = create_text_to_speech_workflow(project, provider=provider, model_ref=model.name)

        before = counts()
        result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertEqual(len(result["node_runs"]), 2)
        self.assertEqual(frappe.db.count("AI Provider Job", {"node_run": ["in", result["node_runs"]]}), 0)
        assert_count_delta(
            self,
            before,
            {
                "AI Workflow Version": 1,
                "AI Workflow Run": 1,
                "AI Node Run": 2,
                "AI Credit Ledger": 1,
            },
        )

    def test_incompatible_provider_model_account_and_pricing_cases_reject_before_side_effects(self):
        cases = (
            self._provider_model_mismatch_case,
            self._model_node_type_mismatch_case,
            self._disabled_model_case,
            self._unpriced_model_case,
            self._provider_account_provider_mismatch_case,
            self._inactive_configured_provider_account_case,
            self._inactive_default_provider_account_case,
            self._missing_default_provider_account_case,
            self._configured_account_project_scope_case,
            self._configured_account_user_scope_case,
        )
        for case_factory in cases:
            with self.subTest(case=case_factory.__name__):
                workflow, expected_message, forbidden_fragments = case_factory()
                before = counts()
                with preflight_policy(slow_ai_run_preflight_require_known_pricing=True):
                    with self.assertRaises(RunPreflightError) as exc:
                        frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)
                self.assertIn(expected_message, str(exc.exception))
                assert_safe_error(self, exc.exception, *forbidden_fragments)
                assert_count_delta(self, before, {})
                self.assertFalse(frappe.db.exists("AI Workflow Version", {"workflow": workflow.name}))
                self.assertFalse(frappe.db.exists("AI Workflow Run", {"workflow": workflow.name}))

    def _provider_model_mismatch_case(self):
        provider = unique("compat-provider")
        other_provider = unique("compat-other-provider")
        project = create_project()
        model = create_model(other_provider, pricing_json={"unit": "run", "amount_usd": "0.05"})
        create_provider_account(provider, project=project.name)
        create_top_up(project.name, "0.20", "Compatibility mismatch credit")
        workflow = create_text_to_image_workflow(project, provider=provider, model_ref=model.name)
        return workflow, "belongs to provider", ()

    def _model_node_type_mismatch_case(self):
        provider = unique("compat-node-provider")
        project = create_project()
        model = create_model(
            provider,
            node_type="provider_text_to_speech",
            pricing_json={"unit": "run", "amount_usd": "0.05"},
        )
        create_provider_account(provider, project=project.name)
        create_top_up(project.name, "0.20", "Compatibility node type credit")
        workflow = create_text_to_image_workflow(project, provider=provider, model_ref=model.name)
        return workflow, "for node type", ()

    def _disabled_model_case(self):
        provider = unique("compat-disabled-provider")
        project = create_project()
        model = create_model(
            provider,
            status="DISABLED",
            pricing_json={"unit": "run", "amount_usd": "0.05"},
        )
        create_provider_account(provider, project=project.name)
        create_top_up(project.name, "0.20", "Compatibility disabled credit")
        workflow = create_text_to_image_workflow(project, provider=provider, model_ref=model.name)
        return workflow, "disabled model", ()

    def _unpriced_model_case(self):
        provider = unique("compat-unpriced-provider")
        project = create_project()
        model = create_model(provider)
        create_provider_account(provider, project=project.name)
        create_top_up(project.name, "0.20", "Compatibility unpriced credit")
        workflow = create_text_to_image_workflow(project, provider=provider, model_ref=model.name)
        return workflow, "without known pricing", ()

    def _provider_account_provider_mismatch_case(self):
        provider = unique("compat-account-provider")
        other_provider = unique("compat-account-other")
        project = create_project()
        model = create_model(provider, pricing_json={"unit": "run", "amount_usd": "0.05"})
        account = create_provider_account(other_provider, is_default=0)
        create_provider_account(provider, project=project.name)
        create_top_up(project.name, "0.20", "Compatibility account provider credit")
        workflow = create_text_to_image_workflow(
            project,
            provider=provider,
            model_ref=model.name,
            provider_account=account.name,
        )
        return workflow, "belongs to provider", (account.name,)

    def _inactive_configured_provider_account_case(self):
        provider = unique("compat-inactive-provider")
        project = create_project()
        model = create_model(provider, pricing_json={"unit": "run", "amount_usd": "0.05"})
        account = create_provider_account(provider, status="DISABLED", is_default=0, project=project.name)
        create_top_up(project.name, "0.20", "Compatibility inactive account credit")
        workflow = create_text_to_image_workflow(
            project,
            provider=provider,
            model_ref=model.name,
            provider_account=account.name,
        )
        return workflow, "is not active", (account.name,)

    def _inactive_default_provider_account_case(self):
        provider = unique("compat-inactive-default")
        project = create_project()
        model = create_model(provider, pricing_json={"unit": "run", "amount_usd": "0.05"})
        create_provider_account(provider, status="DISABLED", project=project.name)
        create_top_up(project.name, "0.20", "Compatibility inactive default credit")
        workflow = create_text_to_image_workflow(project, provider=provider, model_ref=model.name)
        return workflow, "No active default provider account", ()

    def _missing_default_provider_account_case(self):
        provider = unique("compat-missing-default")
        project = create_project()
        model = create_model(provider, pricing_json={"unit": "run", "amount_usd": "0.05"})
        create_top_up(project.name, "0.20", "Compatibility missing default credit")
        workflow = create_text_to_image_workflow(project, provider=provider, model_ref=model.name)
        return workflow, "No active default provider account", ()

    def _configured_account_project_scope_case(self):
        provider = unique("compat-scope-provider")
        project = create_project()
        other_project = create_project("Compatibility Other Project")
        model = create_model(provider, pricing_json={"unit": "run", "amount_usd": "0.05"})
        account = create_provider_account(provider, is_default=0, project=other_project.name)
        create_provider_account(provider, project=project.name)
        create_top_up(project.name, "0.20", "Compatibility scope credit")
        workflow = create_text_to_image_workflow(
            project,
            provider=provider,
            model_ref=model.name,
            provider_account=account.name,
        )
        return workflow, "not allowed", (account.name, other_project.name)

    def _configured_account_user_scope_case(self):
        provider = unique("compat-user-provider")
        project = create_project()
        model = create_model(provider, pricing_json={"unit": "run", "amount_usd": "0.05"})
        account = create_provider_account(provider, is_default=0, project=project.name, user="Guest")
        create_provider_account(provider, project=project.name)
        create_top_up(project.name, "0.20", "Compatibility user scope credit")
        workflow = create_text_to_image_workflow(
            project,
            provider=provider,
            model_ref=model.name,
            provider_account=account.name,
        )
        return workflow, "not allowed", (account.name, "Guest")

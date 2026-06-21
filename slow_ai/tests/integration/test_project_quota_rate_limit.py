import json
from decimal import Decimal
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.billing import create_top_up, get_balance
from slow_ai.domain.exceptions import RunPreflightError


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def create_project(**limits):
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Quota Project"),
            "status": "Open",
            **limits,
        }
    )


def create_model(provider: str, amount_usd: str = "0.05"):
    return insert_doc(
        {
            "doctype": "AI Model",
            "model_id": unique(f"{provider}/model"),
            "model_name": "Quota Test Model",
            "provider": provider,
            "status": "ENABLED",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "amount_usd": amount_usd}),
        }
    )


def create_provider_account(provider: str, *, rate_limit=None):
    return insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": unique("Quota Provider Account"),
            "api_key_secret": "quota-provider-secret",
            "is_default": 1,
            "status": "ACTIVE",
            "rate_limit_json": json.dumps(rate_limit or {}),
        }
    )


def create_text_workflow(project):
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Quota Text Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Quota text"}},
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
    config = {"provider": provider, "model": model_name}
    if provider_account:
        config["provider_account"] = provider_account
    return insert_doc(
        {
            "doctype": "AI Workflow",
            "title": unique("Quota Provider Workflow"),
            "project": project.name,
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Quota prompt"}},
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


def create_published_text_template():
    template = frappe.call(
        "slow_ai.api.templates.save_template",
        template_name=unique("Quota Public Tool"),
        status="DRAFT",
        category="Quota Test",
        description="Quota public tool fixture",
        nodes=json.dumps(
            [
                {"id": "text_prompt_1", "type": "text_prompt", "config": {"text": "Public quota prompt"}},
                {"id": "tool_output_1", "type": "tool_output", "config": {"output_name": "Result"}},
            ]
        ),
        edges=json.dumps(
            [
                {
                    "id": "edge_1",
                    "source": "text_prompt_1",
                    "source_port": "text",
                    "target": "tool_output_1",
                    "target_port": "text",
                }
            ]
        ),
        layout=json.dumps({}),
        input_schema_json=json.dumps([]),
    )
    frappe.call("slow_ai.api.templates.submit_template_for_review", template=template["name"])
    return frappe.call("slow_ai.api.templates.approve_template", template=template["name"])


def side_effect_counts(workflow_name: str, provider: str | None = None, project: str | None = None) -> dict[str, int]:
    counts = {
        "versions": frappe.db.count("AI Workflow Version", {"workflow": workflow_name}),
        "runs": frappe.db.count("AI Workflow Run", {"workflow": workflow_name}),
        "provider_jobs": frappe.db.count("AI Provider Job", {"provider": provider}) if provider else frappe.db.count("AI Provider Job"),
        "reservations": frappe.db.count("AI Credit Ledger", {"project": project, "ledger_type": "RESERVE"})
        if project
        else frappe.db.count("AI Credit Ledger", {"ledger_type": "RESERVE"}),
    }
    counts["node_runs"] = frappe.db.count("AI Node Run")
    return counts


def assert_no_side_effect_change(testcase, before: dict[str, int], workflow_name: str, provider: str | None, project: str):
    after = side_effect_counts(workflow_name, provider=provider, project=project)
    testcase.assertEqual(after, before)


class TestProjectQuotaRateLimit(FrappeTestCase):
    def test_project_max_active_runs_rejects_before_side_effects(self):
        project = create_project(max_active_runs=1)
        active = frappe.call("slow_ai.api.runs.start_run", workflow=create_text_workflow(project).name)
        self.assertEqual(frappe.db.get_value("AI Workflow Run", active["workflow_run"], "status"), "QUEUED")
        provider = unique("quota-project-provider")
        model = create_model(provider)
        create_provider_account(provider)
        create_top_up(project.name, "1.00", "Quota project credit")
        workflow = create_provider_workflow(project, provider=provider, model_name=model.name)
        before = side_effect_counts(workflow.name, provider=provider, project=project.name)

        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertIn("Project active run limit reached", str(exc.exception))
        assert_no_side_effect_change(self, before, workflow.name, provider, project.name)

    def test_duplicate_start_reuses_existing_run_without_quota_rejection(self):
        project = create_project(max_active_runs=1, max_active_runs_per_user=1)
        workflow = create_text_workflow(project)

        first = frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)
        second = frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertEqual(first["workflow_run"], second["workflow_run"])
        self.assertEqual(first["workflow_version"], second["workflow_version"])
        self.assertEqual(frappe.db.count("AI Workflow Run", {"workflow": workflow.name}), 1)

    def test_user_max_active_runs_rejects_correctly(self):
        project = create_project(max_active_runs_per_user=1)
        frappe.call("slow_ai.api.runs.start_run", workflow=create_text_workflow(project).name)
        workflow = create_text_workflow(project)
        before = side_effect_counts(workflow.name, project=project.name)

        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertIn("User active run limit reached", str(exc.exception))
        assert_no_side_effect_change(self, before, workflow.name, None, project.name)

    def test_provider_account_concurrency_rejects_before_provider_job_creation(self):
        project = create_project()
        provider = unique("quota-provider-account-provider")
        model = create_model(provider)
        account = create_provider_account(provider, rate_limit={"max_active_provider_jobs": 1})
        create_top_up(project.name, "1.00", "Quota provider account credit")
        insert_doc(
            {
                "doctype": "AI Provider Job",
                "provider": provider,
                "provider_account": account.name,
                "model": model.name,
                "status": "WAITING_PROVIDER",
                "idempotency_key": unique("quota-active-provider-job"),
            }
        )
        workflow = create_provider_workflow(project, provider=provider, model_name=model.name, provider_account=account.name)
        before = side_effect_counts(workflow.name, provider=provider, project=project.name)

        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertIn("Provider account active job limit reached", str(exc.exception))
        self.assertNotIn(account.name, str(exc.exception))
        self.assertNotIn("quota-provider-secret", str(exc.exception))
        assert_no_side_effect_change(self, before, workflow.name, provider, project.name)

    def test_daily_project_spend_cap_rejects_debit_plus_new_reserve(self):
        project = create_project(daily_project_spend_cap_usd="0.10")
        provider = unique("quota-daily-provider")
        model = create_model(provider, "0.05")
        create_provider_account(provider)
        create_top_up(project.name, "1.00", "Quota daily cap credit")
        insert_doc(
            {
                "doctype": "AI Credit Ledger",
                "project": project.name,
                "ledger_type": "DEBIT",
                "amount_usd": "0.08",
                "currency": "USD",
                "description": "Existing daily spend",
            }
        )
        workflow = create_provider_workflow(project, provider=provider, model_name=model.name)
        before = side_effect_counts(workflow.name, provider=provider, project=project.name)

        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertIn("Daily project spend cap reached", str(exc.exception))
        assert_no_side_effect_change(self, before, workflow.name, provider, project.name)

    def test_daily_user_spend_cap_rejects_user_debit_plus_new_reserve(self):
        project = create_project(daily_user_spend_cap_usd="0.10")
        provider = unique("quota-daily-user-provider")
        model = create_model(provider, "0.05")
        create_provider_account(provider)
        create_top_up(project.name, "1.00", "Quota daily user cap credit")
        insert_doc(
            {
                "doctype": "AI Credit Ledger",
                "project": project.name,
                "ledger_type": "DEBIT",
                "amount_usd": "0.08",
                "currency": "USD",
                "description": "Existing daily user spend",
            }
        )
        workflow = create_provider_workflow(project, provider=provider, model_name=model.name)
        before = side_effect_counts(workflow.name, provider=provider, project=project.name)

        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        self.assertIn("Daily user spend cap reached", str(exc.exception))
        assert_no_side_effect_change(self, before, workflow.name, provider, project.name)

    def test_completed_failed_cancelled_expired_runs_do_not_count_as_active(self):
        for status in ("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"):
            project = create_project(max_active_runs=1)
            first = frappe.call("slow_ai.api.runs.start_run", workflow=create_text_workflow(project).name)
            frappe.db.set_value("AI Workflow Run", first["workflow_run"], "status", status)

            second = frappe.call("slow_ai.api.runs.start_run", workflow=create_text_workflow(project).name)

            self.assertTrue(frappe.db.exists("AI Workflow Run", second["workflow_run"]))

    def test_rejection_payload_is_safe(self):
        project = create_project(max_active_runs=1)
        frappe.call("slow_ai.api.runs.start_run", workflow=create_text_workflow(project).name)
        workflow = create_text_workflow(project)

        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)

        encoded = str(exc.exception)
        self.assertIn("Project active run limit reached", encoded)
        self.assertNotIn("api_key_secret", encoded)
        self.assertNotIn("request_json", encoded)
        self.assertNotIn("response_json", encoded)
        self.assertNotIn("raw_error_json", encoded)
        self.assertNotIn("quota-provider-secret", encoded)

    def test_public_tool_run_start_receives_backend_quota_rejection_safely(self):
        project = create_project(max_active_runs=1)
        frappe.call("slow_ai.api.runs.start_run", workflow=create_text_workflow(project).name)
        template = create_published_text_template()
        draft = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=project.name,
            title="Quota rejected public tool draft",
        )
        before = side_effect_counts(draft["name"], project=project.name)

        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=draft["name"])

        self.assertIn("Project active run limit reached", str(exc.exception))
        assert_no_side_effect_change(self, before, draft["name"], None, project.name)
        self.assertEqual(Decimal(get_balance(project.name)["balance_usd"]), Decimal("0"))

import json
from datetime import timedelta
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from slow_ai.workers.run_workflow import run_workflow
from slow_ai.tests.integration.test_public_tool_page import create_project
from slow_ai.tests.integration.test_public_tool_page import ensure_user
from slow_ai.tests.integration.test_public_tool_page import lineage_side_effect_counts
from slow_ai.tests.integration.test_public_tool_page import save_template
from slow_ai.tests.integration.test_public_tool_page import text_tool_edges
from slow_ai.tests.integration.test_public_tool_page import text_tool_input_schema
from slow_ai.tests.integration.test_public_tool_page import text_tool_nodes
from slow_ai.tests.integration.test_public_tool_page import unique


FORBIDDEN_CLEANUP_RESPONSE_FRAGMENTS = (
    "api_key_secret",
    "request_json",
    "response_json",
    "raw_error_json",
    "Authorization: Bearer",
    "api.wavespeed.ai",
    "api.replicate.com",
    "provider_account",
)


class TestPublicToolDraftCleanup(FrappeTestCase):
    def setUp(self):
        self.previous_user = frappe.session.user
        self.user = ensure_user(f"slow.ai.cleanup.{uuid4().hex[:8]}@example.test")
        frappe.set_user("Administrator")
        self.template = save_template(
            unique("Cleanup Tool Template"),
            "PUBLISHED",
            text_tool_nodes(style="natural", steps=4),
            text_tool_edges(),
            text_tool_input_schema(),
        )
        self.project = create_project(self.user)

    def tearDown(self):
        frappe.set_user(self.previous_user)

    def test_stale_public_tool_draft_with_no_run_is_cleaned(self):
        draft = self._prepare_tool_draft(title="Cleanup Stale Prepared Draft")
        self._age_tool_draft(draft["name"], hours=48)

        counts_before = lineage_side_effect_counts()
        result = self._cleanup(max_age_hours=24)

        self.assertIn(draft["name"], result["deleted_workflows"])
        self.assertFalse(frappe.db.exists("AI Workflow", draft["name"]))
        self.assert_side_effect_counts_unchanged(counts_before)
        self.assert_safe_cleanup_response(result)

    def test_fresh_public_tool_draft_is_not_cleaned(self):
        draft = self._prepare_tool_draft(title="Cleanup Fresh Prepared Draft")

        result = self._cleanup(max_age_hours=24)

        self.assertTrue(frappe.db.exists("AI Workflow", draft["name"]))
        self.assertNotIn(draft["name"], result["deleted_workflows"])
        self.assertIn(
            {"workflow": draft["name"], "reason": "fresh"},
            result["skipped"],
        )

    def test_draft_with_existing_run_is_not_cleaned(self):
        draft = self._prepare_tool_draft(title="Cleanup Started Prepared Draft")
        frappe.set_user(self.user)
        run = frappe.call("slow_ai.api.runs.start_run", workflow=draft["name"])
        self._age_tool_draft(draft["name"], hours=48)
        counts_before = lineage_side_effect_counts()

        result = self._cleanup(max_age_hours=24)

        self.assertTrue(frappe.db.exists("AI Workflow", draft["name"]))
        self.assertTrue(frappe.db.exists("AI Workflow Run", run["workflow_run"]))
        self.assertNotIn(draft["name"], result["deleted_workflows"])
        self.assertIn(
            {"workflow": draft["name"], "reason": "has_run"},
            result["skipped"],
        )
        self.assert_side_effect_counts_unchanged(counts_before)

    def test_normal_canvas_workflow_draft_is_not_cleaned(self):
        frappe.set_user(self.user)
        workflow = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            project=self.project.name,
            title="Cleanup Normal Canvas Draft",
            nodes=json.dumps(text_tool_nodes()),
            edges=json.dumps(text_tool_edges()),
            layout=json.dumps({}),
        )
        self._age_workflow(workflow["name"], hours=48)

        result = self._cleanup(max_age_hours=24)

        self.assertTrue(frappe.db.exists("AI Workflow", workflow["name"]))
        self.assertNotIn(workflow["name"], result["deleted_workflows"])

    def test_stale_rerun_draft_with_no_run_is_cleaned(self):
        source = self._prepare_tool_draft(title="Cleanup Rerun Source Draft")
        frappe.set_user(self.user)
        run = frappe.call("slow_ai.api.runs.start_run", workflow=source["name"])
        run_workflow(run["workflow_run"])
        rerun = frappe.call("slow_ai.api.public_tools.prepare_rerun_from_run", workflow_run=run["workflow_run"])
        rerun_workflow = rerun["workflow"]["name"]
        self._age_tool_draft(rerun_workflow, hours=48)

        counts_before = lineage_side_effect_counts()
        result = self._cleanup(max_age_hours=24)

        self.assertIn(rerun_workflow, result["deleted_workflows"])
        self.assertFalse(frappe.db.exists("AI Workflow", rerun_workflow))
        self.assertTrue(frappe.db.exists("AI Workflow Run", run["workflow_run"]))
        self.assert_side_effect_counts_unchanged(counts_before)

    def test_cleanup_dry_run_and_non_admin_guard(self):
        draft = self._prepare_tool_draft(title="Cleanup Dry Run Draft")
        self._age_tool_draft(draft["name"], hours=48)

        frappe.set_user(self.user)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.public_tools.cleanup_stale_tool_drafts", max_age_hours=24)

        result = self._cleanup(max_age_hours=24, dry_run=1)

        self.assertTrue(result["dry_run"])
        self.assertIn(draft["name"], result["deleted_workflows"])
        self.assertTrue(frappe.db.exists("AI Workflow", draft["name"]))

    def _prepare_tool_draft(self, title: str):
        frappe.set_user(self.user)
        draft = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=self.template["name"],
            project=self.project.name,
            title=title,
            values=json.dumps({"prompt": title, "style": "natural", "steps": 4}),
        )
        self.assertEqual(draft["is_temporary_tool_draft"], 1)
        self.assertEqual(draft["tool_draft_type"], "PREPARED")
        self.assertTrue(draft["tool_draft_prepared_at"])
        return draft

    def _cleanup(self, **kwargs):
        frappe.set_user("Administrator")
        return frappe.call("slow_ai.api.public_tools.cleanup_stale_tool_drafts", **kwargs)

    def _age_tool_draft(self, workflow: str, hours: int):
        old = now_datetime() - timedelta(hours=hours)
        frappe.db.set_value(
            "AI Workflow",
            workflow,
            {
                "tool_draft_prepared_at": old,
                "modified": old,
            },
            update_modified=False,
        )

    def _age_workflow(self, workflow: str, hours: int):
        old = now_datetime() - timedelta(hours=hours)
        frappe.db.set_value("AI Workflow", workflow, "modified", old, update_modified=False)

    def assert_side_effect_counts_unchanged(self, expected: dict[str, int]):
        for doctype, count in expected.items():
            self.assertEqual(frappe.db.count(doctype), count, doctype)

    def assert_safe_cleanup_response(self, response: dict):
        encoded = json.dumps(response, default=str)
        for fragment in FORBIDDEN_CLEANUP_RESPONSE_FRAGMENTS:
            self.assertNotIn(fragment, encoded)

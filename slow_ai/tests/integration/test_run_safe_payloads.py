import json

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.tests.integration.test_run_activity_timeline import add_provider_artifacts
from slow_ai.tests.integration.test_run_activity_timeline import count_side_effect_records
from slow_ai.tests.integration.test_run_activity_timeline import create_manual_run
from slow_ai.tests.integration.test_run_activity_timeline import create_project


SECRET = "sk_test_should_not_leak"
PROVIDER_URL = "https://provider.example.invalid/raw-output.png"


class TestRunSafePayloads(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")

    def create_secret_run(self):
        project = create_project()
        _, _, run = create_manual_run(project, status="FAILED")
        frappe.db.set_value(
            "AI Workflow Run",
            run.name,
            "error_json",
            json.dumps(
                {
                    "message": f"Provider failed Authorization: Bearer {SECRET} at {PROVIDER_URL}",
                    "api_key": SECRET,
                    "raw_error_json": {"token": SECRET},
                }
            ),
        )
        node_run, provider_job, asset = add_provider_artifacts(project, run, provider_status="FAILED", raw_secret=SECRET)
        frappe.db.set_value(
            "AI Node Run",
            node_run.name,
            {
                "output_json": json.dumps(
                    {
                        "asset": asset.name if asset else "AI-ASSET-NOT-FOUND",
                        "api_key": SECRET,
                        "provider_url": PROVIDER_URL,
                        "raw_response": {"token": SECRET},
                    }
                ),
                "error_json": json.dumps(
                    {
                        "message": f"Node failed with token={SECRET} at {PROVIDER_URL}",
                        "secret": SECRET,
                    }
                ),
            },
        )
        frappe.db.set_value(
            "AI Provider Job",
            provider_job.name,
            {
                "provider_account": "AI-PROVIDER-ACCOUNT-SECRET-SHOULD-NOT-LEAK",
                "external_job_id": PROVIDER_URL,
                "raw_error_json": json.dumps(
                    {
                        "message": f"Provider failed api_key={SECRET} at {PROVIDER_URL}",
                        "code": "provider_error",
                        "Authorization": f"Bearer {SECRET}",
                    }
                ),
            },
        )
        return project, run, node_run, provider_job

    def test_get_run_status_returns_safe_error_message_only(self):
        _, run, _, _ = self.create_secret_run()

        status = frappe.call("slow_ai.api.runs.get_run_status", workflow_run=run.name)
        encoded = json.dumps(status, default=str)

        self.assertIsInstance(status["error"], str)
        self.assertIn("[link hidden]", status["error"])
        self.assertNotIn(SECRET, encoded)
        self.assertNotIn("api_key", encoded)
        self.assertNotIn("raw_error_json", encoded)
        self.assertNotIn(PROVIDER_URL, encoded)

    def test_get_history_excludes_raw_provider_fields_and_provider_account(self):
        _, run, _, provider_job = self.create_secret_run()

        history = frappe.call("slow_ai.api.runs.get_history", workflow_run=run.name)
        encoded = json.dumps(history, default=str)
        provider_payload = next(row for row in history["provider_jobs"] if row["name"] == provider_job.name)

        self.assertNotIn("provider_account", provider_payload)
        self.assertNotIn("external_job_id", provider_payload)
        self.assertNotIn("request_json", encoded)
        self.assertNotIn("response_json", encoded)
        self.assertNotIn("raw_error_json", encoded)
        self.assertNotIn(SECRET, encoded)
        self.assertNotIn(PROVIDER_URL, encoded)
        self.assertEqual(provider_payload["error"]["code"], "provider_error")
        self.assertIn("[redacted]", provider_payload["error"]["message"])
        self.assertIn("[link hidden]", provider_payload["error"]["message"])

    def test_get_history_returns_safe_display_summaries_for_ui(self):
        _, run, node_run, provider_job = self.create_secret_run()

        history = frappe.call("slow_ai.api.runs.get_history", workflow_run=run.name)
        node_payload = next(row for row in history["node_runs"] if row["name"] == node_run.name)
        provider_payload = next(row for row in history["provider_jobs"] if row["name"] == provider_job.name)

        self.assertEqual(history["run"]["workflow_run"], run.name)
        self.assertIn("node_id", node_payload)
        self.assertIn("node_type", node_payload)
        self.assertIn("status", node_payload)
        self.assertIn("provider_job", node_payload)
        self.assertIn("input_summary", node_payload)
        self.assertIn("output", node_payload)
        self.assertNotIn("input_json", node_payload)
        self.assertNotIn("output_json", node_payload)
        self.assertNotIn("error_json", node_payload)
        self.assertEqual(provider_payload["name"], provider_job.name)
        self.assertEqual(provider_payload["status"], "FAILED")
        self.assertIn("cost_usd", provider_payload)
        self.assertTrue(history["ledger"] == [] or "amount_usd" in history["ledger"][0])
        for asset in history["assets"]:
            self.assertIn("name", asset)
            self.assertIn("asset_type", asset)
            self.assertNotIn("url", asset)
            self.assertNotIn("file", asset)
            self.assertNotIn("metadata_json", asset)

    def test_timeline_api_remains_safe_after_status_history_hardening(self):
        _, run, _, _ = self.create_secret_run()

        timeline = frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=run.name)
        encoded = json.dumps(timeline, default=str)

        self.assertIn("events", timeline)
        self.assertNotIn(SECRET, encoded)
        self.assertNotIn(PROVIDER_URL, encoded)
        self.assertNotIn("provider_account", encoded)
        self.assertNotIn("raw_error_json", encoded)

    def test_read_calls_create_no_side_effects(self):
        _, run, _, _ = self.create_secret_run()
        before = count_side_effect_records()

        frappe.call("slow_ai.api.runs.get_run_status", workflow_run=run.name)
        frappe.call("slow_ai.api.runs.get_history", workflow_run=run.name)
        frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=run.name)

        self.assertEqual(count_side_effect_records(), before)

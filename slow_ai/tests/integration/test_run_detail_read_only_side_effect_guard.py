import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.tests.integration.test_run_activity_timeline import add_provider_artifacts
from slow_ai.tests.integration.test_run_activity_timeline import create_manual_run
from slow_ai.tests.integration.test_run_activity_timeline import create_project
from slow_ai.tests.integration.test_run_activity_timeline import create_workflow
from slow_ai.tests.integration.test_run_activity_timeline import insert_doc


SIDE_EFFECT_DOCTYPES = (
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
)

MUTATION_SNAPSHOT_FIELDS = {
    "AI Workflow Run": [
        "name",
        "status",
        "is_archived",
        "archived_by",
        "archived_at",
        "error_json",
        "source_template",
        "source_template_version",
    ],
    "AI Node Run": ["name", "workflow_run", "status", "provider_job", "cost_usd", "error_json"],
    "AI Provider Job": [
        "name",
        "node_run",
        "status",
        "poll_attempts",
        "last_polled_at",
        "retry_count",
        "estimated_cost_usd",
        "cost_usd",
        "debit_cost_usd",
        "debit_cost_source",
        "raw_error_json",
    ],
    "AI Asset": [
        "name",
        "source_workflow_run",
        "source_node_run",
        "source_provider_job",
        "url",
        "file",
        "metadata_json",
    ],
    "AI Credit Ledger": [
        "name",
        "workflow_run",
        "node_run",
        "provider_job",
        "ledger_type",
        "amount_usd",
        "currency",
        "metadata_json",
    ],
    "AI Tool Run Share": ["name", "workflow_run", "status", "selected_assets_json", "expires_at"],
}

UNSAFE_FRAGMENTS = (
    "read-only-provider-account-label",
    "AI-PROVIDER-ACCOUNT-READONLY-SECRET",
    "sk_read_only_should_not_leak",
    "https://provider.example.invalid",
    "request_json",
    "response_json",
    "raw_error_json",
    "Authorization",
    "Bearer sk_read_only_should_not_leak",
    "api_key",
    "Traceback",
    "stack trace",
    "draft_nodes_json",
    "draft_edges_json",
    "nodes_json",
    "edges_json",
    "layout_json",
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _record_counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def _mutation_snapshot() -> dict[str, list[dict]]:
    snapshot = {}
    for doctype, fields in MUTATION_SNAPSHOT_FIELDS.items():
        rows = frappe.get_all(doctype, fields=fields, order_by="name asc")
        snapshot[doctype] = [dict(row) for row in rows]
    return json.loads(json.dumps(snapshot, default=str))


def _assert_no_side_effects(testcase: FrappeTestCase, before_counts: dict[str, int], before_snapshot: dict[str, list[dict]]):
    testcase.assertEqual(_record_counts(), before_counts)
    testcase.assertEqual(_mutation_snapshot(), before_snapshot)


def _assert_safe_payload(testcase: FrappeTestCase, payload):
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


def _make_queued_run():
    project = create_project()
    workflow = create_workflow(project.name)
    return project, frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])


def _make_failed_provider_like_run():
    secret = "sk_read_only_should_not_leak"
    project = create_project()
    _, _, run = create_manual_run(project, status="FAILED")
    frappe.db.set_value(
        "AI Workflow Run",
        run.name,
        "error_json",
        json.dumps(
            {
                "message": f"Provider failed Authorization: Bearer {secret} at https://provider.example.invalid/run",
                "api_key": secret,
                "raw_error_json": {"token": secret},
                "stack": "stack trace should not leak",
            }
        ),
    )
    node_run, provider_job, _ = add_provider_artifacts(project, run, provider_status="FAILED", raw_secret=secret)
    frappe.db.set_value(
        "AI Node Run",
        node_run.name,
        {
            "output_json": json.dumps(
                {
                    "asset": "AI-ASSET-NOT-FOUND",
                    "safe_display": "visible summary key",
                    "api_key": secret,
                    "provider_url": "https://provider.example.invalid/node-output",
                    "raw_response": {"Authorization": f"Bearer {secret}"},
                }
            ),
            "error_json": json.dumps(
                {
                    "message": f"Node failed token={secret} at https://provider.example.invalid/node",
                    "secret": secret,
                }
            ),
        },
    )
    account = insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": "timeline_provider",
            "account_label": "read-only-provider-account-label",
            "api_key_secret": secret,
            "status": "ACTIVE",
        }
    )
    frappe.db.set_value(
        "AI Provider Job",
        provider_job.name,
        {
            "provider_account": account.name,
            "external_job_id": "https://provider.example.invalid/external-job",
            "request_json": json.dumps({"Authorization": f"Bearer {secret}"}),
            "response_json": json.dumps({"output": "https://provider.example.invalid/raw-output.png", "secret": secret}),
            "raw_error_json": json.dumps(
                {
                    "message": f"Provider failed api_key={secret} at https://provider.example.invalid/error",
                    "code": "provider_error",
                    "Authorization": f"Bearer {secret}",
                }
            ),
        },
    )
    return project, run, node_run, provider_job


class TestRunDetailReadOnlySideEffectGuard(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_authenticated_and_guest_run_detail_reads_are_side_effect_free_and_safe(self):
        _, queued = _make_queued_run()
        project = create_project()
        _, _, succeeded_run = create_manual_run(project, status="SUCCEEDED")
        succeeded_node_run, succeeded_provider_job, selected_asset = add_provider_artifacts(
            project,
            succeeded_run,
            raw_secret="sk_read_only_should_not_leak",
        )
        frappe.db.set_value(
            "AI Node Run",
            succeeded_node_run.name,
            "output_json",
            json.dumps({"asset": selected_asset.name, "display": "safe output summary"}),
        )
        frappe.db.set_value(
            "AI Asset",
            selected_asset.name,
            "metadata_json",
            json.dumps(
                {
                    "origin": "read-only-guard",
                    "provider_secret": "sk_read_only_should_not_leak",
                    "nested": {
                        "provider_url": "https://provider.example.invalid/metadata",
                        "safe_note": "kept",
                    },
                    "notes": "Authorization: Bearer sk_read_only_should_not_leak https://provider.example.invalid/meta",
                }
            ),
        )
        archived_project = create_project()
        _, _, archived_run = create_manual_run(archived_project, status="SUCCEEDED", archived=True)
        _, failed_run, _, _ = _make_failed_provider_like_run()
        share = insert_doc(
            {
                "doctype": "AI Tool Run Share",
                "workflow_run": succeeded_run.name,
                "project": project.name,
                "share_token": _unique("read-only-share-token"),
                "status": "ACTIVE",
                "selected_assets_json": json.dumps([selected_asset.name]),
            }
        )
        before_counts = _record_counts()
        before_snapshot = _mutation_snapshot()

        authenticated_payloads = [
            frappe.call("slow_ai.api.runs.get_run_status", workflow_run=queued["workflow_run"]),
            frappe.call("slow_ai.api.runs.get_run_status", workflow_run=succeeded_run.name),
            frappe.call("slow_ai.api.runs.get_history", workflow_run=succeeded_run.name),
            frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=succeeded_run.name),
            frappe.call("slow_ai.api.runs.get_run_status", workflow_run=failed_run.name),
            frappe.call("slow_ai.api.runs.get_history", workflow_run=failed_run.name),
            frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=failed_run.name),
            frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=succeeded_run.name),
            frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=failed_run.name),
            frappe.call("slow_ai.api.public_tools.get_my_run", workflow_run=archived_run.name),
            frappe.call("slow_ai.api.public_tools.get_run_output_gallery", workflow_run=succeeded_run.name),
            frappe.call("slow_ai.api.public_tools.list_my_runs", project=project.name),
            frappe.call("slow_ai.api.public_tools.list_my_runs", project=archived_project.name, include_archived=1),
            frappe.call("slow_ai.api.assets.view", asset=selected_asset.name),
        ]

        for payload in authenticated_payloads:
            _assert_safe_payload(self, payload)
        _assert_no_side_effects(self, before_counts, before_snapshot)

        asset_view = authenticated_payloads[-1]
        self.assertEqual(asset_view["metadata"]["origin"], "read-only-guard")
        self.assertEqual(asset_view["metadata"]["nested"]["safe_note"], "kept")
        self.assertNotIn("provider_secret", asset_view["metadata"])
        self.assertNotIn("provider_url", asset_view["metadata"]["nested"])
        self.assertIn("[link hidden]", asset_view["metadata"]["notes"])

        detail = authenticated_payloads[7]
        failed_detail = authenticated_payloads[8]
        self.assertTrue(detail["node_runs"][0]["output"]["has_output"])
        self.assertIn(selected_asset.name, detail["node_runs"][0]["asset_names"])
        failed_node = next(row for row in failed_detail["node_runs"] if row["node_id"] == "provider_1")
        self.assertEqual(failed_node["output"]["keys"], ["asset", "safe_display"])
        self.assertNotIn("api_key", failed_node["output"]["keys"])

        frappe.set_user("Guest")
        shared_payload = frappe.call("slow_ai.api.public_tools.get_shared_run", share_token=share.share_token)
        _assert_safe_payload(self, shared_payload)
        self.assertEqual({row["name"] for row in shared_payload["assets"]}, {selected_asset.name})

        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_counts, before_snapshot)
        self.assertEqual(
            frappe.db.get_value("AI Provider Job", succeeded_provider_job.name, "poll_attempts"),
            before_snapshot["AI Provider Job"][
                [row["name"] for row in before_snapshot["AI Provider Job"]].index(succeeded_provider_job.name)
            ]["poll_attempts"],
        )

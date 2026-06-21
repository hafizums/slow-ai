import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date
from frappe.utils import now_datetime

from slow_ai.workers.run_workflow import run_workflow


SIDE_EFFECT_DOCTYPES = (
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
)


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def create_project(owner: str = "Administrator"):
    project = insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Timeline Project"),
            "status": "Open",
        }
    )
    frappe.db.set_value("AI Project", project.name, "owner", owner)
    project.reload()
    return project


def create_user(email: str) -> str:
    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
        user.enabled = 1
        user.user_type = "System User"
        user.save(ignore_permissions=True)
    else:
        user = insert_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Timeline",
                "last_name": "User",
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
                "roles": [{"role": "Desk User"}],
            }
        )
    if "Desk User" not in {row.role for row in user.get("roles", [])}:
        user.append("roles", {"role": "Desk User"})
        user.save(ignore_permissions=True)
    return email


def workflow_nodes():
    return [
        {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Timeline prompt"}},
        {"id": "output_1", "type": "export_output", "config": {}},
    ]


def workflow_edges():
    return [
        {
            "id": "edge_1",
            "source": "prompt_1",
            "source_port": "text",
            "target": "output_1",
            "target_port": "text",
        }
    ]


def create_workflow(project: str):
    return frappe.call(
        "slow_ai.api.workflows.save_workflow",
        project=project,
        title=unique("Timeline Workflow"),
        nodes=workflow_nodes(),
        edges=workflow_edges(),
        layout={},
    )


def create_manual_run(project, *, status: str = "SUCCEEDED", archived: bool = False):
    workflow = create_workflow(project.name)
    version = insert_doc(
        {
            "doctype": "AI Workflow Version",
            "workflow": workflow["name"],
            "version_no": 1,
            "snapshot_hash": unique("timeline-hash"),
            "created_by": "Administrator",
            "created_at": now_datetime(),
            "nodes_json": json.dumps(workflow_nodes()),
            "edges_json": json.dumps(workflow_edges()),
            "layout_json": "{}",
        }
    )
    queued_at = add_to_date(now_datetime(), seconds=-60)
    started_at = add_to_date(now_datetime(), seconds=-50)
    completed_at = add_to_date(now_datetime(), seconds=-10) if status in {"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"} else None
    run = insert_doc(
        {
            "doctype": "AI Workflow Run",
            "project": project.name,
            "workflow": workflow["name"],
            "workflow_version": version.name,
            "status": status,
            "queued_at": queued_at,
            "started_at": started_at,
            "completed_at": completed_at,
            "is_archived": 1 if archived else 0,
            "archived_at": now_datetime() if archived else None,
            "error_json": json.dumps(
                {
                    "message": "safe persisted message",
                    "provider_account": "SHOULD_NOT_LEAK",
                    "raw_error_json": {"api_key": "SHOULD_NOT_LEAK"},
                }
            ),
        }
    )
    return workflow, version, run


def add_provider_artifacts(project, run, *, provider_status: str = "SUCCEEDED", raw_secret: str = "SHOULD_NOT_LEAK"):
    node_run = insert_doc(
        {
            "doctype": "AI Node Run",
            "workflow_run": run.name,
            "node_id": "provider_1",
            "node_type": "provider_text_to_image",
            "status": "SUCCEEDED" if provider_status == "SUCCEEDED" else "FAILED",
            "attempt_no": 1,
            "started_at": add_to_date(now_datetime(), seconds=-45),
            "completed_at": add_to_date(now_datetime(), seconds=-20),
            "error_json": json.dumps({"raw_error_json": raw_secret, "api_key": raw_secret}),
        }
    )
    model = insert_doc(
        {
            "doctype": "AI Model",
            "model_id": unique("timeline/model"),
            "model_name": "Timeline Test Model",
            "provider": "timeline_provider",
            "status": "ENABLED",
            "modality": "TEXT_TO_IMAGE",
        }
    )
    provider_job = insert_doc(
        {
            "doctype": "AI Provider Job",
            "node_run": node_run.name,
            "provider": "timeline_provider",
            "model": model.name,
            "external_job_id": "https://provider.example.invalid/raw-job-url",
            "status": provider_status,
            "idempotency_key": unique("timeline-provider-job"),
            "estimated_cost_usd": 0.04,
            "cost_usd": 0.03 if provider_status == "SUCCEEDED" else 0,
            "submitted_at": add_to_date(now_datetime(), seconds=-42),
            "last_polled_at": add_to_date(now_datetime(), seconds=-18),
            "poll_attempts": 2,
            "completed_at": add_to_date(now_datetime(), seconds=-15),
            "request_json": json.dumps({"api_key": raw_secret, "url": "https://provider.example.invalid/request"}),
            "response_json": json.dumps({"secret": raw_secret, "url": "https://provider.example.invalid/response"}),
            "raw_error_json": json.dumps({"secret": raw_secret, "raw_provider_url": "https://provider.example.invalid/error"}),
        }
    )
    node_run.provider_job = provider_job.name
    node_run.save(ignore_permissions=True)

    asset = None
    if provider_status == "SUCCEEDED":
        asset = insert_doc(
            {
                "doctype": "AI Asset",
                "project": project.name,
                "asset_type": "IMAGE",
                "url": "https://safe-assets.example.invalid/timeline.png",
                "mime_type": "image/png",
                "source_workflow_run": run.name,
                "source_node_run": node_run.name,
                "source_provider_job": provider_job.name,
                "metadata_json": json.dumps({"provider_secret": raw_secret}),
            }
        )
        for ledger_type, amount in (("RESERVE", 0.04), ("DEBIT", 0.03), ("RELEASE", 0.01)):
            insert_doc(
                {
                    "doctype": "AI Credit Ledger",
                    "project": project.name,
                    "workflow_run": run.name,
                    "node_run": node_run.name,
                    "provider_job": provider_job.name,
                    "ledger_type": ledger_type,
                    "amount_usd": amount,
                    "currency": "USD",
                    "description": f"Timeline {ledger_type.lower()}",
                    "metadata_json": json.dumps({"secret": raw_secret}),
                }
            )
    return node_run, provider_job, asset


def count_side_effect_records() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


class TestRunActivityTimeline(FrappeTestCase):
    def tearDown(self):
        frappe.set_user("Administrator")

    def test_successful_run_returns_ordered_safe_timeline_events(self):
        project = create_project()
        workflow = create_workflow(project.name)
        start_result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])
        run_workflow(start_result["workflow_run"])

        timeline = frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=start_result["workflow_run"])
        event_types = [event["event_type"] for event in timeline["events"]]
        timestamps = [str(event["timestamp"]) for event in timeline["events"]]

        self.assertIn("RUN_QUEUED", event_types)
        self.assertIn("RUN_STARTED", event_types)
        self.assertIn("NODE_STARTED", event_types)
        self.assertIn("RUN_SUCCEEDED", event_types)
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertEqual(timeline["run"]["workflow_run"], start_result["workflow_run"])

    def test_provider_run_timeline_includes_provider_asset_reservation_release_and_debit_events(self):
        project = create_project()
        _, _, run = create_manual_run(project)
        add_provider_artifacts(project, run)

        timeline = frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=run.name)
        event_types = {event["event_type"] for event in timeline["events"]}

        self.assertIn("PROVIDER_JOB_CREATED", event_types)
        self.assertIn("PROVIDER_JOB_SUBMITTED", event_types)
        self.assertIn("PROVIDER_JOB_POLLED", event_types)
        self.assertIn("PROVIDER_JOB_SUCCEEDED", event_types)
        self.assertIn("ASSET_CREATED", event_types)
        self.assertIn("CREDIT_RESERVED", event_types)
        self.assertIn("CREDIT_DEBITED", event_types)
        self.assertIn("CREDIT_RELEASED", event_types)
        debit_events = [event for event in timeline["events"] if event["event_type"] == "CREDIT_DEBITED"]
        self.assertEqual(debit_events[0]["amount_usd"], "0.0300")
        self.assertEqual(debit_events[0]["currency"], "USD")

    def test_failed_or_expired_provider_timeline_uses_safe_failure_events(self):
        project = create_project()
        _, _, run = create_manual_run(project, status="FAILED")
        add_provider_artifacts(project, run, provider_status="EXPIRED", raw_secret="TIMELINE_SECRET")

        timeline = frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=run.name)
        payload = json.dumps(timeline, default=str)
        event_types = {event["event_type"] for event in timeline["events"]}

        self.assertIn("PROVIDER_JOB_EXPIRED", event_types)
        self.assertIn("RUN_FAILED", event_types)
        self.assertNotIn("TIMELINE_SECRET", payload)
        self.assertNotIn("raw_error_json", payload)
        self.assertNotIn("request_json", payload)
        self.assertNotIn("response_json", payload)
        self.assertNotIn("https://provider.example.invalid", payload)

    def test_cancelled_run_timeline_shows_safe_cancellation(self):
        project = create_project()
        _, _, run = create_manual_run(project, status="CANCELLED")
        add_provider_artifacts(project, run, provider_status="CANCELLED", raw_secret="CANCEL_SECRET")

        timeline = frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=run.name)
        payload = json.dumps(timeline, default=str)
        event_types = {event["event_type"] for event in timeline["events"]}

        self.assertIn("RUN_CANCELLED", event_types)
        self.assertNotIn("CANCEL_SECRET", payload)
        self.assertNotIn("provider_account", payload)

    def test_archived_run_timeline_shows_archive_event(self):
        project = create_project()
        _, _, run = create_manual_run(project, archived=True)

        timeline = frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=run.name)
        event_types = {event["event_type"] for event in timeline["events"]}

        self.assertIn("RUN_ARCHIVED", event_types)
        self.assertEqual(timeline["run"]["is_archived"], 1)

    def test_timeline_api_enforces_project_view_access(self):
        owner = create_user(f"timeline-owner-{uuid4().hex[:8]}@example.invalid")
        outsider = create_user(f"timeline-outsider-{uuid4().hex[:8]}@example.invalid")
        project = create_project(owner=owner)
        _, _, run = create_manual_run(project)

        frappe.set_user(outsider)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=run.name)

    def test_timeline_read_creates_no_execution_or_billing_side_effects(self):
        project = create_project()
        _, _, run = create_manual_run(project)
        add_provider_artifacts(project, run)
        before = count_side_effect_records()

        frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=run.name)

        self.assertEqual(count_side_effect_records(), before)

    def test_timeline_can_include_share_events_without_exposing_share_token(self):
        project = create_project()
        _, _, run = create_manual_run(project)
        share = insert_doc(
            {
                "doctype": "AI Tool Run Share",
                "workflow_run": run.name,
                "project": project.name,
                "share_token": unique("secret-share-token"),
                "status": "ACTIVE",
                "selected_assets_json": json.dumps([]),
            }
        )

        timeline = frappe.call("slow_ai.api.runs.get_run_timeline", workflow_run=run.name)
        payload = json.dumps(timeline, default=str)
        share_events = [event for event in timeline["events"] if event["event_type"] == "RUN_SHARED"]

        self.assertEqual(share_events[0]["related_name"], share.name)
        self.assertNotIn(share.share_token, payload)

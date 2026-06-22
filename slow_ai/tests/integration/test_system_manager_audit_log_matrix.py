import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.tests.integration.test_project_membership import create_project
from slow_ai.tests.integration.test_project_membership import ensure_user
from slow_ai.tests.integration.test_public_tool_page import create_shareable_asset_run
from slow_ai.tests.integration.test_public_tool_page import save_template
from slow_ai.tests.integration.test_public_tool_page import text_tool_edges
from slow_ai.tests.integration.test_public_tool_page import text_tool_nodes
from slow_ai.tests.integration.test_run_recovery_admin_tools import _make_provider_waiting_run


AUDIT_SIDE_EFFECT_DOCTYPES = (
    "Version",
    "AI Project Member",
    "AI Provider Account",
    "AI Model",
    "AI Workflow Template",
    "AI Workflow Template Version",
    "AI Workflow",
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
)

UNSAFE_FRAGMENTS = (
    "audit-provider-secret",
    "raw-recovery-secret",
    "request_json",
    "response_json",
    "raw_error_json",
    "Authorization",
    "Bearer",
    "api_key",
    "Traceback",
)


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in AUDIT_SIDE_EFFECT_DOCTYPES}


def version_count(doctype: str, docname: str) -> int:
    return frappe.db.count("Version", {"ref_doctype": doctype, "docname": docname})


def assert_business_audit(testcase: FrappeTestCase, doctype: str, docname: str, *, owner: str | None = None):
    row = frappe.db.get_value(doctype, docname, ["owner", "creation", "modified", "modified_by"], as_dict=True)
    testcase.assertTrue(row, f"{doctype} {docname} should exist")
    testcase.assertTrue(row.creation)
    testcase.assertTrue(row.modified)
    if owner:
        testcase.assertEqual(row.owner, owner)
    testcase.assertTrue(row.modified_by)


def assert_safe_payload(testcase: FrappeTestCase, payload):
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


class TestSystemManagerAuditLogMatrix(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"audit.owner.{uuid4().hex[:8]}@example.test")
        self.member = ensure_user(f"audit.member.{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"audit.outsider.{uuid4().hex[:8]}@example.test")
        self.project = create_project(self.owner)

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_system_manager_governance_actions_leave_existing_audit_trails(self):
        member = frappe.call(
            "slow_ai.api.projects.add_member",
            project=self.project.name,
            user=self.member,
            role="VIEWER",
        )["member"]
        assert_business_audit(self, "AI Project Member", member["name"], owner="Administrator")
        before_member_versions = version_count("AI Project Member", member["name"])
        updated_member = frappe.call("slow_ai.api.projects.update_member_role", member=member["name"], role="EDITOR")[
            "member"
        ]
        disabled_member = frappe.call("slow_ai.api.projects.disable_member", member=member["name"])["member"]
        self.assertEqual(updated_member["role"], "EDITOR")
        self.assertEqual(disabled_member["status"], "DISABLED")
        self.assertGreaterEqual(version_count("AI Project Member", member["name"]), before_member_versions)

        account = frappe.call(
            "slow_ai.api.provider_accounts.create_account",
            provider=unique("audit-provider"),
            account_label=unique("Audit Provider Account"),
            api_key="audit-provider-secret",
            project=self.project.name,
            is_default=1,
        )["account"]
        assert_business_audit(self, "AI Provider Account", account["name"], owner="Administrator")
        defaulted = frappe.call("slow_ai.api.provider_accounts.set_default", account=account["name"])["account"]
        disabled = frappe.call("slow_ai.api.provider_accounts.disable_account", account=account["name"])["account"]
        self.assertEqual(defaulted["is_default"], 1)
        self.assertEqual(disabled["status"], "DISABLED")
        assert_business_audit(self, "AI Provider Account", account["name"], owner="Administrator")

        model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": unique("audit-provider/model"),
                "model_name": "Audit Matrix Model",
                "provider": account["provider"],
                "status": "ENABLED",
                "modality": "TEXT_TO_IMAGE",
                "node_type": "provider_text_to_image",
                "category": "provider",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": "0.01"}),
            }
        )
        before_model_versions = version_count("AI Model", model.name)
        frappe.call("slow_ai.api.models.update_model_status", model=model.name, status="DISABLED")
        frappe.call("slow_ai.api.models.update_model_pricing", model=model.name, amount_usd="0.02")
        frappe.call(
            "slow_ai.api.models.update_model_metadata",
            model=model.name,
            capabilities={"safe_note": "audit capability"},
            input_metadata={"width": 512},
            output_metadata={"mime_type": "image/png"},
        )
        assert_business_audit(self, "AI Model", model.name)
        self.assertGreaterEqual(version_count("AI Model", model.name), before_model_versions)

        approved = save_template(unique("Audit Approved Template"), "PUBLISHED", text_tool_nodes(), text_tool_edges())
        version_name = approved["published_version"]
        rolled_back = frappe.call(
            "slow_ai.api.templates.rollback_template_to_version",
            template=approved["name"],
            template_version=version_name,
            review_notes="Audit rollback",
        )
        archived = frappe.call("slow_ai.api.templates.archive_template", template=approved["name"], reason="Audit archive")
        rejected = save_template(unique("Audit Rejected Template"), "REJECTED", text_tool_nodes(), text_tool_edges())
        self.assertEqual(rolled_back["status"], "PUBLISHED")
        self.assertEqual(archived["status"], "ARCHIVED")
        self.assertEqual(rejected["status"], "REJECTED")
        assert_business_audit(self, "AI Workflow Template", approved["name"])
        assert_business_audit(self, "AI Workflow Template Version", version_name)
        self.assertGreaterEqual(frappe.db.count("AI Workflow Template Version", {"template": approved["name"]}), 2)

        top_up = frappe.call(
            "slow_ai.api.billing.create_top_up",
            project=self.project.name,
            amount_usd="3.00",
            description="Audit top up",
        )
        assert_business_audit(self, "AI Credit Ledger", top_up["ledger"]["name"], owner="Administrator")

        share_run = create_shareable_asset_run(self.owner, title="Audit Share Run")
        frappe.set_user(self.owner)
        share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=share_run["run"]["workflow_run"],
            selected_assets=[share_run["asset"].name],
        )["share"]
        disabled_share = frappe.call("slow_ai.api.public_tools.disable_run_share", share_token=share["share_token"])["share"]
        self.assertEqual(disabled_share["status"], "DISABLED")
        assert_business_audit(self, "AI Tool Run Share", share["name"], owner=self.owner)

    def test_run_recovery_audit_and_safe_payloads(self):
        frappe.set_user("Administrator")
        project, _, start, adapter, provider_job = _make_provider_waiting_run()
        inspected = frappe.call("slow_ai.api.runs.inspect_run_recovery", workflow_run=start.workflow_run, max_age_minutes=0)
        before_resume = counts()
        resumed = frappe.call("slow_ai.api.runs.resume_run", workflow_run=start.workflow_run)
        after_resume = counts()
        expired = frappe.call(
            "slow_ai.api.runs.expire_stuck_run",
            workflow_run=start.workflow_run,
            max_age_minutes=0,
            reason="Audit recovery expiry",
        )

        assert_safe_payload(self, inspected)
        assert_safe_payload(self, resumed)
        assert_safe_payload(self, expired)
        self.assertEqual(after_resume, before_resume)
        self.assertEqual(resumed["queue_job_id"], f"slow_ai:workflow_run:{start.workflow_run}")
        self.assertEqual(expired["run"]["status"], "EXPIRED")
        self.assertEqual(frappe.db.get_value("AI Provider Job", provider_job.name, "status"), "CANCELLED")
        self.assertEqual(adapter.polled, [])
        assert_business_audit(self, "AI Workflow Run", start.workflow_run)
        assert_business_audit(self, "AI Provider Job", provider_job.name)
        self.assertEqual(frappe.db.count("AI Asset", {"source_provider_job": provider_job.name}), 0)
        self.assertEqual(frappe.db.count("AI Credit Ledger", {"workflow_run": start.workflow_run, "ledger_type": "RELEASE"}), 1)
        self.assertTrue(project.name)

    def test_rejected_governance_actions_do_not_create_misleading_records(self):
        model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": unique("audit-denied-provider/model"),
                "model_name": "Denied Audit Model",
                "provider": unique("audit-denied-provider"),
                "status": "ENABLED",
                "modality": "TEXT_TO_IMAGE",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": "0.01"}),
            }
        )
        draft = save_template(unique("Audit Denied Draft"), "DRAFT", text_tool_nodes(), text_tool_edges())
        before = counts()

        frappe.set_user(self.outsider)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.models.update_model_status", model=model.name, status="DISABLED")
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.billing.create_top_up",
                project=self.project.name,
                amount_usd="1.00",
                description="Denied audit top up",
            )
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.projects.add_member",
                project=self.project.name,
                user=self.outsider,
                role="VIEWER",
            )
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.templates.submit_template_for_review",
                template=draft["name"],
            )

        self.assertEqual(counts(), before)

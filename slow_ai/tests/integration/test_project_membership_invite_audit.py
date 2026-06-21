import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.tests.integration.test_project_membership import create_project
from slow_ai.tests.integration.test_project_membership import ensure_user
from slow_ai.tests.integration.test_project_membership import save_text_workflow


SIDE_EFFECT_DOCTYPES = (
    "AI Project Member",
    "AI Workflow",
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
)

MUTATION_SNAPSHOT_FIELDS = {
    "AI Project Member": ["name", "project", "user", "role", "status", "modified"],
    "AI Workflow": ["name", "project", "status", "modified"],
    "AI Workflow Run": ["name", "status", "modified"],
    "AI Node Run": ["name", "status", "modified"],
    "AI Provider Job": ["name", "status", "modified"],
    "AI Asset": ["name", "project", "modified"],
    "AI Credit Ledger": ["name", "project", "ledger_type", "amount_usd", "modified"],
    "AI Tool Run Share": ["name", "workflow_run", "status", "modified"],
}

UNSAFE_FRAGMENTS = (
    "provider_account",
    "api_key_secret",
    "request_json",
    "response_json",
    "raw_error_json",
    "Authorization",
    "Bearer",
    "api.wavespeed.ai",
    "api.replicate.com",
    "draft_nodes_json",
    "draft_edges_json",
    "layout_json",
    "AI Provider Job",
    "AI Credit Ledger",
)


def _counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def _snapshot() -> dict[str, list[dict]]:
    snapshot = {}
    for doctype, fields in MUTATION_SNAPSHOT_FIELDS.items():
        snapshot[doctype] = [dict(row) for row in frappe.get_all(doctype, fields=fields, order_by="name asc")]
    return json.loads(json.dumps(snapshot, default=str))


def _assert_no_side_effects(testcase: FrappeTestCase, before_counts: dict[str, int], before_snapshot: dict[str, list[dict]]):
    testcase.assertEqual(_counts(), before_counts)
    testcase.assertEqual(_snapshot(), before_snapshot)


def _assert_only_member_delta(testcase: FrappeTestCase, before_counts: dict[str, int], delta: int):
    after = _counts()
    for doctype in SIDE_EFFECT_DOCTYPES:
        expected_delta = delta if doctype == "AI Project Member" else 0
        testcase.assertEqual(after[doctype], before_counts[doctype] + expected_delta, doctype)


def _assert_safe_payload(testcase: FrappeTestCase, payload):
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


class TestProjectMembershipInviteAudit(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"membership.audit.owner.{uuid4().hex[:8]}@example.test")
        self.owner_member = ensure_user(f"membership.audit.owner.member.{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"membership.audit.editor.{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"membership.audit.viewer.{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"membership.audit.billing.{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"membership.audit.outsider.{uuid4().hex[:8]}@example.test")
        self.candidate = ensure_user(f"membership.audit.candidate.{uuid4().hex[:8]}@example.test")
        self.project = create_project(self.owner)

    def tearDown(self):
        frappe.set_user("Administrator")

    def _add_member(self, user: str, role: str):
        frappe.set_user(self.owner)
        return frappe.call("slow_ai.api.projects.add_member", project=self.project.name, user=user, role=role)["member"]

    def test_owner_member_and_system_manager_can_manage_members_with_safe_audit_payloads(self):
        member_meta = frappe.get_meta("AI Project Member")
        self.assertTrue(member_meta.track_changes)

        before_add = _counts()
        frappe.set_user(self.owner)
        added = frappe.call(
            "slow_ai.api.projects.add_member",
            project=self.project.name,
            user=self.owner_member,
            role="OWNER",
        )
        _assert_safe_payload(self, added)
        self.assertEqual(added["member"]["role"], "OWNER")
        _assert_only_member_delta(self, before_add, 1)

        before_update_versions = frappe.db.count("Version", {"ref_doctype": "AI Project Member", "docname": added["member"]["name"]})
        frappe.set_user(self.owner_member)
        updated = frappe.call("slow_ai.api.projects.update_member_role", member=added["member"]["name"], role="EDITOR")
        _assert_safe_payload(self, updated)
        self.assertEqual(updated["member"]["role"], "EDITOR")
        self.assertGreaterEqual(
            frappe.db.count("Version", {"ref_doctype": "AI Project Member", "docname": added["member"]["name"]}),
            before_update_versions,
        )

        frappe.set_user("Administrator")
        disabled = frappe.call("slow_ai.api.projects.disable_member", member=added["member"]["name"])
        listed = frappe.call("slow_ai.api.projects.list_members", project=self.project.name)
        _assert_safe_payload(self, disabled)
        _assert_safe_payload(self, listed)
        self.assertEqual(disabled["member"]["status"], "DISABLED")
        self.assertIn(added["member"]["name"], {row["name"] for row in listed["members"]})

    def test_non_managers_cannot_mutate_memberships_and_rejections_have_no_side_effects(self):
        self._add_member(self.editor, "EDITOR")
        self._add_member(self.viewer, "VIEWER")
        self._add_member(self.billing, "BILLING")

        for user in (self.editor, self.viewer, self.billing, self.outsider, "Guest"):
            before_counts = _counts()
            before_snapshot = _snapshot()
            frappe.set_user(user)
            for method, kwargs in (
                ("slow_ai.api.projects.add_member", {"project": self.project.name, "user": self.candidate, "role": "VIEWER"}),
                (
                    "slow_ai.api.projects.update_member_role",
                    {"member": frappe.db.get_value("AI Project Member", {"project": self.project.name, "user": self.viewer}), "role": "EDITOR"},
                ),
                (
                    "slow_ai.api.projects.disable_member",
                    {"member": frappe.db.get_value("AI Project Member", {"project": self.project.name, "user": self.viewer})},
                ),
                ("slow_ai.api.projects.list_members", {"project": self.project.name}),
            ):
                with self.assertRaises(frappe.PermissionError):
                    frappe.call(method, **kwargs)
            frappe.set_user("Administrator")
            _assert_no_side_effects(self, before_counts, before_snapshot)

    def test_role_changes_and_disable_immediately_affect_project_read_and_write_access(self):
        member = self._add_member(self.viewer, "VIEWER")
        frappe.set_user(self.owner)
        workflow = save_text_workflow(self.project.name, "Membership Audit Access Workflow")

        frappe.set_user(self.viewer)
        read_payload = frappe.call("slow_ai.api.workflows.get_workflow", workflow=workflow["name"])
        self.assertEqual(read_payload["name"], workflow["name"])
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])

        before_role_change = _counts()
        frappe.set_user(self.owner)
        updated = frappe.call("slow_ai.api.projects.update_member_role", member=member["name"], role="EDITOR")
        _assert_safe_payload(self, updated)
        _assert_only_member_delta(self, before_role_change, 0)

        frappe.set_user(self.viewer)
        started = frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])
        self.assertTrue(started["workflow_run"])

        before_disable = _counts()
        frappe.set_user(self.owner)
        disabled = frappe.call("slow_ai.api.projects.disable_member", member=member["name"])
        _assert_safe_payload(self, disabled)
        _assert_only_member_delta(self, before_disable, 0)

        frappe.set_user(self.viewer)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.workflows.get_workflow", workflow=workflow["name"])
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])

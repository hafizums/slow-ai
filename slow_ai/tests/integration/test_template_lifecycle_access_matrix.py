import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.tests.integration.test_project_membership import ensure_user
from slow_ai.tests.integration.test_public_tool_page import add_member
from slow_ai.tests.integration.test_public_tool_page import create_project
from slow_ai.tests.integration.test_public_tool_page import text_tool_edges
from slow_ai.tests.integration.test_public_tool_page import text_tool_input_schema
from slow_ai.tests.integration.test_public_tool_page import text_tool_nodes


SIDE_EFFECT_DOCTYPES = (
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

SNAPSHOT_FIELDS = {
    "AI Workflow Template": [
        "name",
        "status",
        "published_version",
        "submitted_by",
        "reviewed_by",
        "review_notes",
        "rejection_reason",
        "nodes_json",
        "edges_json",
        "input_schema_json",
        "modified",
    ],
    "AI Workflow Template Version": ["name", "template", "version_no", "status", "snapshot_hash", "modified"],
    "AI Workflow": ["name", "project", "source_template", "source_template_version", "modified"],
    "AI Workflow Version": ["name", "workflow", "snapshot_hash", "modified"],
    "AI Workflow Run": ["name", "workflow", "status", "source_template", "source_template_version", "modified"],
    "AI Node Run": ["name", "workflow_run", "status", "modified"],
    "AI Provider Job": ["name", "node_run", "status", "modified"],
    "AI Asset": ["name", "project", "source_workflow_run", "modified"],
    "AI Credit Ledger": ["name", "project", "workflow_run", "ledger_type", "amount_usd", "modified"],
    "AI Tool Run Share": ["name", "workflow_run", "status", "modified"],
}

UNSAFE_FRAGMENTS = (
    "TEMPLATE_ACCESS_SECRET",
    "template-access-provider-account",
    "https://provider.example.invalid",
    "api_key",
    "api_key_secret",
    "Authorization",
    "Bearer",
    "provider_account",
    "request_json",
    "response_json",
    "raw_error_json",
)


def unique(prefix: str) -> str:
    return f"{prefix} {uuid4().hex[:8]}"


def counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def snapshot() -> dict[str, list[dict]]:
    rows = {}
    for doctype, fields in SNAPSHOT_FIELDS.items():
        rows[doctype] = [dict(row) for row in frappe.get_all(doctype, fields=fields, order_by="name asc")]
    return json.loads(json.dumps(rows, default=str))


def assert_no_side_effects(testcase: FrappeTestCase, before_counts: dict[str, int], before_snapshot: dict) -> None:
    testcase.assertEqual(counts(), before_counts)
    testcase.assertEqual(snapshot(), before_snapshot)


def assert_safe_payload(testcase: FrappeTestCase, payload) -> None:
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


def save_draft_template_as(user: str, *, name: str | None = None, text: str = "Template access prompt") -> dict:
    previous = frappe.session.user
    frappe.set_user(user)
    try:
        return frappe.call(
            "slow_ai.api.templates.save_template",
            template_name=name or unique("Template Access Draft"),
            status="DRAFT",
            category="Access Matrix",
            description="Template lifecycle access matrix fixture",
            nodes=json.dumps(text_tool_nodes(text, style="natural", steps=4)),
            edges=json.dumps(text_tool_edges()),
            layout=json.dumps({"nodes": [{"id": "prompt_1", "x": 96, "y": 128}]}),
            input_schema_json=json.dumps(text_tool_input_schema()),
        )
    finally:
        frappe.set_user(previous)


def submit_template_as(user: str, template: str) -> dict:
    previous = frappe.session.user
    frappe.set_user(user)
    try:
        return frappe.call("slow_ai.api.templates.submit_template_for_review", template=template)
    finally:
        frappe.set_user(previous)


def approve_template(template: str, notes: str = "access matrix approval") -> dict:
    previous = frappe.session.user
    frappe.set_user("Administrator")
    try:
        return frappe.call("slow_ai.api.templates.approve_template", template=template, review_notes=notes)
    finally:
        frappe.set_user(previous)


def create_published_template(owner: str, *, text: str = "Published access prompt") -> dict:
    draft = save_draft_template_as(owner, text=text)
    submit_template_as(owner, draft["name"])
    return approve_template(draft["name"])


class TestTemplateLifecycleAccessMatrix(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"template-access-owner-{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"template-access-editor-{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"template-access-viewer-{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"template-access-billing-{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"template-access-outsider-{uuid4().hex[:8]}@example.test")
        self.project = create_project(self.owner)
        add_member(self.project.name, self.editor, "EDITOR")
        add_member(self.project.name, self.viewer, "VIEWER")
        add_member(self.project.name, self.billing, "BILLING")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_internal_template_reads_are_owner_or_system_manager_only_and_read_only(self):
        own_template = save_draft_template_as(self.owner)
        other_template = save_draft_template_as(self.outsider)
        before_counts = counts()
        before_snapshot = snapshot()

        frappe.set_user(self.owner)
        listed = frappe.call("slow_ai.api.templates.list_templates", status="DRAFT", category="Access Matrix")
        loaded = frappe.call("slow_ai.api.templates.get_template", template=own_template["name"])
        self.assertIn(own_template["name"], {row["name"] for row in listed["templates"]})
        self.assertNotIn(other_template["name"], {row["name"] for row in listed["templates"]})
        self.assertEqual(loaded["name"], own_template["name"])
        assert_safe_payload(self, {"listed": listed, "loaded": loaded})

        frappe.set_user("Administrator")
        admin_listed = frappe.call("slow_ai.api.templates.list_templates", status="DRAFT", category="Access Matrix")
        self.assertIn(own_template["name"], {row["name"] for row in admin_listed["templates"]})
        self.assertIn(other_template["name"], {row["name"] for row in admin_listed["templates"]})

        for user in (self.editor, self.viewer, self.billing, self.outsider):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):
                frappe.call("slow_ai.api.templates.get_template", template=own_template["name"])
            filtered = frappe.call("slow_ai.api.templates.list_templates", status="DRAFT", category="Access Matrix")
            self.assertNotIn(own_template["name"], {row["name"] for row in filtered["templates"]})

        frappe.set_user("Guest")
        for method, kwargs in (
            ("slow_ai.api.templates.list_templates", {"status": "DRAFT"}),
            ("slow_ai.api.templates.get_template", {"template": own_template["name"]}),
            (
                "slow_ai.api.templates.save_template",
                {
                    "template_name": unique("Guest Template"),
                    "status": "DRAFT",
                    "category": "Access Matrix",
                    "description": "Guest denied",
                    "nodes": json.dumps(text_tool_nodes()),
                    "edges": json.dumps(text_tool_edges()),
                },
            ),
        ):
            with self.assertRaises(frappe.PermissionError, msg=method):
                frappe.call(method, **kwargs)

        frappe.set_user("Administrator")
        assert_no_side_effects(self, before_counts, before_snapshot)

    def test_template_review_actions_are_role_scoped_and_rejected_actions_are_side_effect_free(self):
        draft = save_draft_template_as(self.owner)
        before_denied = counts()
        before_denied_snapshot = snapshot()
        for user in (self.editor, self.viewer, self.billing, self.outsider, "Guest"):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):
                frappe.call("slow_ai.api.templates.submit_template_for_review", template=draft["name"])
        frappe.set_user("Administrator")
        assert_no_side_effects(self, before_denied, before_denied_snapshot)

        submitted = submit_template_as(self.owner, draft["name"])
        self.assertEqual(submitted["status"], "IN_REVIEW")

        for user in (self.owner, self.editor, self.viewer, self.billing, self.outsider, "Guest"):
            before_counts = counts()
            before_snapshot = snapshot()
            frappe.set_user(user)
            for method, kwargs in (
                ("slow_ai.api.templates.approve_template", {"template": draft["name"]}),
                ("slow_ai.api.templates.reject_template", {"template": draft["name"], "rejection_reason": "No"}),
                ("slow_ai.api.templates.archive_template", {"template": draft["name"], "reason": "No"}),
            ):
                with self.assertRaises(frappe.PermissionError, msg=f"{user} unexpectedly called {method}"):
                    frappe.call(method, **kwargs)
            frappe.set_user("Administrator")
            assert_no_side_effects(self, before_counts, before_snapshot)

        before_approve = counts()
        approved = approve_template(draft["name"])
        self.assertEqual(approved["status"], "PUBLISHED")
        self.assertEqual(counts()["AI Workflow Template Version"], before_approve["AI Workflow Template Version"] + 1)

    def test_direct_save_cannot_bypass_review_or_unsafe_input_schema(self):
        draft = save_draft_template_as(self.owner)
        before_counts = counts()
        before_snapshot = snapshot()

        for user in (self.owner, "Administrator"):
            frappe.set_user(user)
            for status in ("IN_REVIEW", "PUBLISHED", "ARCHIVED"):
                with self.assertRaises(frappe.ValidationError):
                    frappe.call(
                        "slow_ai.api.templates.save_template",
                        template=draft["name"],
                        template_name=draft["template_name"],
                        status=status,
                        category="Access Matrix",
                        description="Direct bypass denied",
                        nodes=json.dumps(draft["nodes"]),
                        edges=json.dumps(draft["edges"]),
                        layout=json.dumps(draft["layout"]),
                        input_schema_json=json.dumps(draft["input_schema"]),
                    )

        unsafe_nodes = text_tool_nodes()
        unsafe_nodes[0]["config"]["provider_account"] = "template-access-provider-account"
        with self.assertRaises(frappe.ValidationError):
            frappe.call(
                "slow_ai.api.templates.save_template",
                template_name=unique("Unsafe Input Schema"),
                status="DRAFT",
                category="Access Matrix",
                description="Unsafe schema denied",
                nodes=json.dumps(unsafe_nodes),
                edges=json.dumps(text_tool_edges()),
                input_schema_json=json.dumps(
                    [
                        {
                            "id": "provider_account",
                            "label": "Provider Account",
                            "input_type": "TEXT",
                            "target_node_id": "prompt_1",
                            "target_config_field": "provider_account",
                        }
                    ]
                ),
            )

        frappe.set_user("Administrator")
        assert_no_side_effects(self, before_counts, before_snapshot)

    def test_public_tool_template_apis_expose_only_published_active_versions(self):
        draft = save_draft_template_as(self.owner, name=unique("Draft Public Hidden"))
        in_review = save_draft_template_as(self.owner, name=unique("Review Public Hidden"))
        rejected = save_draft_template_as(self.owner, name=unique("Rejected Public Hidden"))
        published = create_published_template(self.owner, text="Visible public prompt")
        archived = create_published_template(self.owner, text="Archived public prompt")
        submit_template_as(self.owner, in_review["name"])
        submit_template_as(self.owner, rejected["name"])
        frappe.set_user("Administrator")
        frappe.call("slow_ai.api.templates.reject_template", template=rejected["name"], rejection_reason="Hidden")
        frappe.call("slow_ai.api.templates.archive_template", template=archived["name"], reason="Hidden")

        before_counts = counts()
        before_snapshot = snapshot()
        frappe.set_user(self.owner)
        listed = frappe.call("slow_ai.api.public_tools.list_templates")
        visible_names = {row["name"] for row in listed["templates"]}
        loaded = frappe.call("slow_ai.api.public_tools.get_template", template=published["name"])

        self.assertIn(published["name"], visible_names)
        for hidden in (draft, in_review, rejected, archived):
            self.assertNotIn(hidden["name"], visible_names)
            with self.assertRaises(frappe.PermissionError):
                frappe.call("slow_ai.api.public_tools.get_template", template=hidden["name"])
        self.assertEqual(loaded["template_version"], published["published_version"])
        self.assertEqual(loaded["nodes"][0]["config"]["text"], "Visible public prompt")
        assert_safe_payload(self, {"listed": listed, "loaded": loaded})

        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.public_tools.list_templates")

        frappe.set_user("Administrator")
        assert_no_side_effects(self, before_counts, before_snapshot)

    def test_template_rollback_is_system_manager_only_and_creates_only_template_version(self):
        template = create_published_template(self.owner, text="Rollback v1 prompt")
        first_version = template["published_version"]
        frappe.set_user(self.owner)
        edited = frappe.call(
            "slow_ai.api.templates.save_template",
            template=template["name"],
            template_name=template["template_name"],
            status="DRAFT",
            category="Access Matrix",
            description="Template lifecycle access matrix fixture",
            nodes=json.dumps(text_tool_nodes("Rollback v2 prompt", style="natural", steps=4)),
            edges=json.dumps(text_tool_edges()),
            layout=json.dumps({"nodes": [{"id": "prompt_1", "x": 96, "y": 128}]}),
            input_schema_json=json.dumps(text_tool_input_schema()),
        )
        submit_template_as(self.owner, edited["name"])
        second = approve_template(template["name"], notes="v2 approval")

        for user in (self.owner, self.editor, self.viewer, self.billing, self.outsider, "Guest"):
            before_counts = counts()
            before_snapshot = snapshot()
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "slow_ai.api.templates.rollback_template_to_version",
                    template=template["name"],
                    template_version=first_version,
                    review_notes="denied rollback",
                )
            frappe.set_user("Administrator")
            assert_no_side_effects(self, before_counts, before_snapshot)

        before_allowed = counts()
        rolled_back = frappe.call(
            "slow_ai.api.templates.rollback_template_to_version",
            template=template["name"],
            template_version=first_version,
            review_notes="allowed rollback",
        )
        public_payload = frappe.call("slow_ai.api.public_tools.get_template", template=template["name"])

        self.assertEqual(rolled_back["status"], "PUBLISHED")
        self.assertNotEqual(public_payload["template_version"], first_version)
        self.assertNotEqual(public_payload["template_version"], second["published_version"])
        self.assertEqual(public_payload["nodes"][0]["config"]["text"], "Rollback v1 prompt")
        self.assertEqual(counts()["AI Workflow Template Version"], before_allowed["AI Workflow Template Version"] + 1)
        self.assertEqual(counts()["AI Workflow Run"], before_allowed["AI Workflow Run"])
        self.assertEqual(counts()["AI Provider Job"], before_allowed["AI Provider Job"])

    def test_internal_and_public_template_workflow_creation_access_and_lineage(self):
        template = create_published_template(self.owner, text="Lineage prompt")
        before_public = counts()

        frappe.set_user(self.editor)
        public_draft = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=self.project.name,
            values={"prompt": "Lineage edited prompt", "style": "studio", "steps": 5},
        )
        run = frappe.call("slow_ai.api.runs.start_run", workflow=public_draft["name"])
        run_doc = frappe.get_doc("AI Workflow Run", run["workflow_run"])

        self.assertEqual(public_draft["source_template"], template["name"])
        self.assertEqual(public_draft["source_template_version"], template["published_version"])
        self.assertEqual(run_doc.source_template, template["name"])
        self.assertEqual(run_doc.source_template_version, template["published_version"])
        self.assertEqual(counts()["AI Provider Job"], before_public["AI Provider Job"])

        internal_template = save_draft_template_as(self.owner, text="Internal template")
        before_denied = counts()
        before_denied_snapshot = snapshot()
        frappe.set_user(self.editor)
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.templates.create_workflow_from_template",
                template=internal_template["name"],
                project=self.project.name,
                title="Denied internal template",
            )
        frappe.set_user("Administrator")
        assert_no_side_effects(self, before_denied, before_denied_snapshot)

        frappe.set_user(self.owner)
        before_allowed = counts()
        created = frappe.call(
            "slow_ai.api.templates.create_workflow_from_template",
            template=internal_template["name"],
            project=self.project.name,
            title="Allowed internal template",
        )
        self.assertTrue(frappe.db.exists("AI Workflow", created["name"]))
        self.assertEqual(counts()["AI Workflow"], before_allowed["AI Workflow"] + 1)
        self.assertEqual(counts()["AI Workflow Run"], before_allowed["AI Workflow Run"])

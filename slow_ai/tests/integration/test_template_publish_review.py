import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import update_password


def unique(prefix: str) -> str:
    return f"{prefix} {uuid4().hex[:8]}"


def ensure_user(email: str):
    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
        user.enabled = 1
        user.user_type = "System User"
        user.save(ignore_permissions=True)
    else:
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Slow AI",
                "last_name": "Template Reviewer",
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
                "roles": [{"role": "Desk User"}],
            }
        ).insert(ignore_permissions=True)
    roles = {row.role for row in user.get("roles", [])}
    if "Desk User" not in roles:
        user.append("roles", {"role": "Desk User"})
        user.save(ignore_permissions=True)
    update_password(email, "SlowAiReview!2345")
    return email


def create_project(owner: str):
    project = frappe.get_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Template Review Project"),
            "status": "Open",
        }
    ).insert(ignore_permissions=True)
    frappe.db.set_value("AI Project", project.name, "owner", owner)
    project.reload()
    return project


def text_nodes(text: str = "Review template prompt"):
    return [
        {
            "id": "prompt_1",
            "type": "text_prompt",
            "label": "Prompt",
            "position": {"x": 96, "y": 128},
            "config": {"text": text},
        },
        {
            "id": "tool_output_1",
            "type": "tool_output",
            "label": "Tool Output",
            "position": {"x": 376, "y": 128},
            "config": {
                "output_name": "answer",
                "description": "Primary output",
                "schema": {"type": "string"},
            },
        },
    ]


def text_edges():
    return [
        {
            "id": "edge_1",
            "source": "prompt_1",
            "source_port": "text",
            "target": "tool_output_1",
            "target_port": "text",
        }
    ]


def safe_input_schema():
    return [
        {
            "id": "prompt",
            "label": "Prompt",
            "input_type": "LONG_TEXT",
            "target_node_id": "prompt_1",
            "target_config_field": "text",
            "required": True,
        }
    ]


def save_draft_template(name: str, owner: str):
    previous_user = frappe.session.user
    frappe.set_user(owner)
    try:
        return frappe.call(
            "slow_ai.api.templates.save_template",
            template_name=name,
            status="DRAFT",
            category="Review",
            description="Template review fixture",
            nodes=json.dumps(text_nodes()),
            edges=json.dumps(text_edges()),
            layout=json.dumps({"nodes": [{"id": "prompt_1", "x": 96, "y": 128}]}),
            input_schema_json=json.dumps(safe_input_schema()),
        )
    finally:
        frappe.set_user(previous_user)


def insert_raw_template(status: str, nodes, edges, input_schema=None, owner: str = "Administrator"):
    doc = frappe.get_doc(
        {
            "doctype": "AI Workflow Template",
            "template_name": unique("Raw Review Template"),
            "status": status,
            "category": "Review",
            "description": "Raw review fixture",
            "nodes_json": json.dumps(nodes),
            "edges_json": json.dumps(edges),
            "layout_json": json.dumps({"nodes": []}),
            "input_schema_json": json.dumps(input_schema or []),
        }
    ).insert(ignore_permissions=True)
    frappe.db.set_value("AI Workflow Template", doc.name, "owner", owner)
    doc.reload()
    return doc


def side_effect_counts():
    return {
        "AI Workflow Version": frappe.db.count("AI Workflow Version"),
        "AI Workflow Run": frappe.db.count("AI Workflow Run"),
        "AI Node Run": frappe.db.count("AI Node Run"),
        "AI Provider Job": frappe.db.count("AI Provider Job"),
        "AI Asset": frappe.db.count("AI Asset"),
        "AI Credit Ledger": frappe.db.count("AI Credit Ledger"),
    }


class TestTemplatePublishReview(FrappeTestCase):
    def setUp(self):
        self.previous_user = frappe.session.user
        self.owner = ensure_user(f"slow.ai.review.owner.{uuid4().hex[:8]}@example.test")
        self.other = ensure_user(f"slow.ai.review.other.{uuid4().hex[:8]}@example.test")
        frappe.set_user("Administrator")
        self.project = create_project(self.owner)

    def tearDown(self):
        frappe.set_user(self.previous_user)

    def test_owner_submit_and_system_manager_approve_makes_template_public(self):
        draft = save_draft_template(unique("Review Draft"), self.owner)
        before = side_effect_counts()

        frappe.set_user(self.owner)
        submitted = frappe.call("slow_ai.api.templates.submit_template_for_review", template=draft["name"])
        self.assertEqual(submitted["status"], "IN_REVIEW")
        self.assertEqual(submitted["submitted_by"], self.owner)
        self.assertTrue(submitted["submitted_at"])

        frappe.set_user("Administrator")
        approved = frappe.call(
            "slow_ai.api.templates.approve_template",
            template=draft["name"],
            review_notes="Looks safe.",
        )
        self.assertEqual(approved["status"], "PUBLISHED")
        self.assertEqual(approved["reviewed_by"], "Administrator")
        self.assertEqual(approved["review_notes"], "Looks safe.")
        self.assertTrue(approved["published_at"])

        frappe.set_user(self.owner)
        listed = frappe.call("slow_ai.api.public_tools.list_templates")
        loaded = frappe.call("slow_ai.api.public_tools.get_template", template=draft["name"])
        prepared = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=draft["name"],
            project=self.project.name,
            values={"prompt": "Approved public prompt"},
        )

        self.assertIn(draft["name"], {row["name"] for row in listed["templates"]})
        self.assertEqual(loaded["status"], "PUBLISHED")
        self.assertEqual(prepared["nodes"][0]["config"]["text"], "Approved public prompt")
        self.assertEqual(before, side_effect_counts())

    def test_save_template_cannot_directly_set_review_controlled_statuses(self):
        before = side_effect_counts()

        frappe.set_user("Administrator")
        for status in ("IN_REVIEW", "PUBLISHED", "ARCHIVED"):
            with self.assertRaises(frappe.ValidationError):
                frappe.call(
                    "slow_ai.api.templates.save_template",
                    template_name=unique(f"Direct {status}"),
                    status=status,
                    category="Review",
                    description="Direct lifecycle bypass fixture",
                    nodes=json.dumps(text_nodes()),
                    edges=json.dumps(text_edges()),
                    layout=json.dumps({"nodes": [{"id": "prompt_1", "x": 96, "y": 128}]}),
                    input_schema_json=json.dumps(safe_input_schema()),
                )

        draft = save_draft_template(unique("Review Direct Update"), self.owner)
        for status in ("IN_REVIEW", "PUBLISHED", "ARCHIVED"):
            with self.assertRaises(frappe.ValidationError):
                frappe.call(
                    "slow_ai.api.templates.save_template",
                    template=draft["name"],
                    template_name=draft["template_name"],
                    status=status,
                    category="Review",
                    description="Direct lifecycle update bypass fixture",
                    nodes=json.dumps(draft["nodes"]),
                    edges=json.dumps(draft["edges"]),
                    layout=json.dumps(draft["layout"]),
                    input_schema_json=json.dumps(draft["input_schema"]),
                )

        self.assertEqual(before, side_effect_counts())

    def test_owner_cannot_directly_save_non_draft_lifecycle_status(self):
        draft = save_draft_template(unique("Owner Direct Review"), self.owner)
        before = side_effect_counts()

        frappe.set_user(self.owner)
        for status in ("IN_REVIEW", "PUBLISHED", "ARCHIVED", "REJECTED"):
            with self.assertRaises(frappe.ValidationError):
                frappe.call(
                    "slow_ai.api.templates.save_template",
                    template=draft["name"],
                    template_name=draft["template_name"],
                    status=status,
                    category="Review",
                    description="Owner direct lifecycle bypass fixture",
                    nodes=json.dumps(draft["nodes"]),
                    edges=json.dumps(draft["edges"]),
                    layout=json.dumps(draft["layout"]),
                    input_schema_json=json.dumps(draft["input_schema"]),
                )

        self.assertEqual(before, side_effect_counts())

    def test_non_owner_cannot_submit_another_users_draft(self):
        draft = save_draft_template(unique("Review Ownership"), self.owner)

        frappe.set_user(self.other)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.templates.submit_template_for_review", template=draft["name"])

    def test_system_manager_rejects_and_owner_can_resubmit_rejected_template(self):
        draft = save_draft_template(unique("Review Reject"), self.owner)
        frappe.set_user(self.owner)
        frappe.call("slow_ai.api.templates.submit_template_for_review", template=draft["name"])

        frappe.set_user("Administrator")
        rejected = frappe.call(
            "slow_ai.api.templates.reject_template",
            template=draft["name"],
            rejection_reason="Needs clearer description.",
        )
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(rejected["rejection_reason"], "Needs clearer description.")

        frappe.set_user(self.owner)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.public_tools.get_template", template=draft["name"])
        resubmitted = frappe.call("slow_ai.api.templates.submit_template_for_review", template=draft["name"])
        self.assertEqual(resubmitted["status"], "IN_REVIEW")

    def test_archive_hides_template_from_public_tools(self):
        draft = save_draft_template(unique("Review Archive"), self.owner)
        frappe.set_user(self.owner)
        frappe.call("slow_ai.api.templates.submit_template_for_review", template=draft["name"])
        frappe.set_user("Administrator")
        frappe.call("slow_ai.api.templates.approve_template", template=draft["name"])
        archived = frappe.call("slow_ai.api.templates.archive_template", template=draft["name"], reason="Retired")
        self.assertEqual(archived["status"], "ARCHIVED")

        frappe.set_user(self.owner)
        listed = frappe.call("slow_ai.api.public_tools.list_templates")
        self.assertNotIn(draft["name"], {row["name"] for row in listed["templates"]})
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.public_tools.get_template", template=draft["name"])

    def test_public_tool_apis_reject_every_non_published_status(self):
        names_by_status = {}
        for status in ("DRAFT", "IN_REVIEW", "REJECTED", "ARCHIVED"):
            doc = insert_raw_template(status, text_nodes(), text_edges(), safe_input_schema(), owner=self.owner)
            names_by_status[status] = doc.name

        frappe.set_user(self.owner)
        listed = frappe.call("slow_ai.api.public_tools.list_templates")
        listed_names = {row["name"] for row in listed["templates"]}
        for status, name in names_by_status.items():
            self.assertNotIn(name, listed_names, status)
            with self.assertRaises(frappe.PermissionError):
                frappe.call("slow_ai.api.public_tools.get_template", template=name)
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "slow_ai.api.public_tools.prepare_workflow_from_template",
                    template=name,
                    project=self.project.name,
                    values={"prompt": "Rejected"},
                )

    def test_approval_validates_graph_and_unsafe_input_schema(self):
        invalid_graph = insert_raw_template(
            "IN_REVIEW",
            text_nodes(),
            [
                {
                    "id": "bad_edge",
                    "source": "missing",
                    "source_port": "text",
                    "target": "tool_output_1",
                    "target_port": "text",
                }
            ],
            safe_input_schema(),
            owner=self.owner,
        )
        unsafe_schema = insert_raw_template(
            "IN_REVIEW",
            [
                {
                    "id": "prompt_1",
                    "type": "text_prompt",
                    "label": "Prompt",
                    "position": {"x": 96, "y": 128},
                    "config": {"text": "Provider prompt"},
                },
                {
                    "id": "provider_1",
                    "type": "provider_text_to_image",
                    "label": "Provider",
                    "position": {"x": 376, "y": 128},
                    "config": {"provider": "review-provider", "model": "review/model"},
                },
                {
                    "id": "output_1",
                    "type": "export_output",
                    "label": "Output",
                    "position": {"x": 656, "y": 128},
                    "config": {},
                },
            ],
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
            ],
            [
                {
                    "id": "account",
                    "input_type": "TEXT",
                    "target_node_id": "provider_1",
                    "target_config_field": "provider_account",
                }
            ],
            owner=self.owner,
        )
        before = side_effect_counts()

        frappe.set_user("Administrator")
        with self.assertRaises(Exception):
            frappe.call("slow_ai.api.templates.approve_template", template=invalid_graph.name)
        with self.assertRaises(frappe.ValidationError):
            frappe.call("slow_ai.api.templates.approve_template", template=unsafe_schema.name)

        self.assertEqual(before, side_effect_counts())

    def test_review_actions_expose_no_provider_secret_and_create_no_execution_records(self):
        draft = save_draft_template(unique("Review Side Effects"), self.owner)
        before = side_effect_counts()

        frappe.set_user(self.owner)
        submitted = frappe.call("slow_ai.api.templates.submit_template_for_review", template=draft["name"])
        frappe.set_user("Administrator")
        approved = frappe.call("slow_ai.api.templates.approve_template", template=draft["name"])
        encoded = json.dumps({"submitted": submitted, "approved": approved}, default=str)

        self.assertEqual("PUBLISHED", approved["status"])
        self.assertNotIn("api_key_secret", encoded)
        self.assertNotIn("provider_account", encoded)
        self.assertNotIn("request_json", encoded)
        self.assertNotIn("response_json", encoded)
        self.assertNotIn("raw_error_json", encoded)
        self.assertEqual(before, side_effect_counts())

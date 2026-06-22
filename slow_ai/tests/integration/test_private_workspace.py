import json

import frappe
from frappe.desk.desktop import get_workspace_sidebar_items
from frappe.tests.utils import FrappeTestCase

from slow_ai.doctype.contracts import PERMANENT_DOCTYPES
from slow_ai.infrastructure.workspace import (
    ADMIN_PAGE,
    WORKSPACE_PAGE,
    WORKSPACE_TITLE,
    sync_private_workspace_for_user,
)


FORBIDDEN_WORKSPACE_FRAGMENTS = (
    "WAVESPEED_API_KEY",
    "api_key_secret",
    "Authorization: Bearer",
    "ProviderAdapter",
    "ProviderRegistry",
    "WorkflowExecutor",
    "run_workflow",
    "submit_job",
    "poll_job",
    "checkpoint",
    "KSampler",
    "CUDA",
    "local model",
)


class TestPrivateWorkspace(FrappeTestCase):
    def setUp(self):
        frappe.reload_doc("slow_ai", "page", "slow_ai_canvas")
        frappe.reload_doc("slow_ai", "page", "slow_ai_admin")

    def test_private_workspace_is_created_for_system_user(self):
        workspace_name = sync_private_workspace_for_user("Administrator")
        sync_private_workspace_for_user("Administrator")
        workspace = frappe.get_doc("Workspace", workspace_name)

        self.assertEqual(workspace.title, WORKSPACE_TITLE)
        self.assertEqual(workspace.module, "Slow Ai")
        self.assertEqual(workspace.public, 0)
        self.assertEqual(workspace.for_user, "Administrator")
        self.assertEqual(workspace.hide_custom, 1)
        self.assertEqual(workspace.is_hidden, 0)
        self.assertEqual(
            frappe.db.count("Workspace", {"name": workspace_name, "for_user": "Administrator"}),
            1,
        )

    def test_private_workspace_links_are_navigation_only(self):
        workspace = frappe.get_doc("Workspace", sync_private_workspace_for_user("Administrator"))
        content = json.loads(workspace.content)
        source = json.dumps(workspace.as_dict(), default=str, sort_keys=True)

        self.assertIn({"type": "shortcut", "data": {"shortcut_name": "Canvas", "col": 3}}, content)
        self.assertIn({"type": "shortcut", "data": {"shortcut_name": "Admin Health", "col": 3}}, content)
        self.assertIn(
            ("Canvas", "Page", WORKSPACE_PAGE),
            {(link.label, link.link_type, link.link_to) for link in workspace.links if link.type == "Link"},
        )
        self.assertIn(
            ("Admin Health", "Page", ADMIN_PAGE),
            {(link.label, link.link_type, link.link_to) for link in workspace.links if link.type == "Link"},
        )
        workspace_doctypes = {
            link.link_to
            for link in workspace.links
            if link.type == "Link" and link.link_type == "DocType"
        }
        self.assertTrue(set(PERMANENT_DOCTYPES).issubset(workspace_doctypes))
        self.assertEqual(set(workspace.charts), set())
        self.assertEqual(set(workspace.number_cards), set())
        self.assertFalse(any(fragment in source for fragment in FORBIDDEN_WORKSPACE_FRAGMENTS))

    def test_private_workspace_appears_in_user_sidebar(self):
        workspace_name = sync_private_workspace_for_user("Administrator")
        previous_user = frappe.session.user
        try:
            frappe.set_user("Administrator")
            sidebar = get_workspace_sidebar_items()
        finally:
            frappe.set_user(previous_user)

        self.assertIn(workspace_name, {item["name"] for item in sidebar["pages"]})

import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from slow_ai.tests.integration.test_public_tool_page import add_member
from slow_ai.tests.integration.test_public_tool_page import create_shareable_asset_run
from slow_ai.tests.integration.test_public_tool_page import create_text_tool_run
from slow_ai.tests.integration.test_public_tool_page import ensure_user
from slow_ai.tests.integration.test_public_tool_page import insert_doc


SIDE_EFFECT_DOCTYPES = (
    "AI Workflow",
    "AI Workflow Version",
    "AI Workflow Run",
    "AI Node Run",
    "AI Provider Job",
    "AI Asset",
    "AI Credit Ledger",
    "AI Tool Run Share",
)

GUEST_UNSAFE_FRAGMENTS = (
    "share-token-provider-secret",
    "share-token-provider-account",
    "share-token-external-job",
    "share-token-raw-url",
    "provider_account",
    "source_provider_job",
    "external_job_id",
    "request_json",
    "response_json",
    "raw_error_json",
    "api_key",
    "Authorization",
    "Bearer",
    "Traceback",
    "draft_nodes_json",
    "draft_edges_json",
    "nodes_json",
    "edges_json",
    "layout_json",
)

AUTHENTICATED_UNSAFE_FRAGMENTS = tuple(
    fragment for fragment in GUEST_UNSAFE_FRAGMENTS if fragment != "source_provider_job"
)

FORBIDDEN_SHARED_PAGE_METHODS = (
    "slow_ai.api.assets.view",
    "slow_ai.api.runs.get_run_status",
    "slow_ai.api.runs.get_history",
    "slow_ai.api.runs.get_run_timeline",
    "slow_ai.api.public_tools.get_my_run",
    "slow_ai.api.public_tools.get_run_output_gallery",
    "slow_ai.api.public_tools.cancel_my_run",
    "slow_ai.api.public_tools.archive_my_run",
    "slow_ai.api.public_tools.prepare_rerun_from_run",
    "slow_ai.api.runs.start_run",
    "slow_ai.api.provider_accounts.",
    "slow_ai.api.billing.",
    "slow_ai.api.models.",
    "slow_ai.api.runs.inspect_run_recovery",
    "slow_ai.api.runs.expire_stuck_run",
    "slow_ai.api.runs.resume_run",
)


def _counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def _assert_counts_delta(testcase: FrappeTestCase, before: dict[str, int], delta: dict[str, int]) -> None:
    after = _counts()
    for doctype, count in before.items():
        testcase.assertEqual(after[doctype], count + delta.get(doctype, 0), doctype)


def _assert_safe_payload(
    testcase: FrappeTestCase,
    payload,
    *extra_forbidden: str,
    fragments: tuple[str, ...] = GUEST_UNSAFE_FRAGMENTS,
) -> None:
    encoded = json.dumps(payload, default=str)
    for fragment in fragments + tuple(extra_forbidden):
        testcase.assertNotIn(fragment, encoded, fragment)


def _add_unsafe_provider_job(created: dict) -> str:
    node_run = frappe.db.get_value(
        "AI Node Run",
        {"workflow_run": created["run"]["workflow_run"], "node_id": "tool_output_1"},
        "name",
    )
    account = insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": "share-token-provider",
            "account_label": f"share-token-provider-account-{uuid4().hex[:8]}",
            "api_key_secret": "share-token-provider-secret",
            "status": "ACTIVE",
        }
    )
    provider_job = insert_doc(
        {
            "doctype": "AI Provider Job",
            "node_run": node_run,
            "provider": "share-token-provider",
            "provider_account": account.name,
            "status": "SUCCEEDED",
            "external_job_id": f"share-token-external-job-{uuid4().hex[:8]}",
            "request_json": json.dumps({"Authorization": "Bearer share-token-provider-secret"}),
            "response_json": json.dumps({"url": "https://provider.example.invalid/share-token-raw-url.png"}),
            "raw_error_json": json.dumps({"api_key": "share-token-provider-secret"}),
        }
    )
    frappe.db.set_value("AI Node Run", node_run, "provider_job", provider_job.name)
    return provider_job.name


class TestShareTokenSecurityMatrix(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"share-token-owner-{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"share-token-editor-{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"share-token-viewer-{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"share-token-billing-{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"share-token-outsider-{uuid4().hex[:8]}@example.test")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_owner_editor_share_create_reuse_disable_and_guest_selected_only_payload(self):
        created = create_shareable_asset_run(self.owner, title="Share Token Security Run")
        provider_job = _add_unsafe_provider_job(created)
        add_member(created["project"].name, self.editor, "EDITOR")
        add_member(created["project"].name, self.viewer, "VIEWER")
        add_member(created["project"].name, self.billing, "BILLING")

        frappe.set_user(self.owner)
        before_owner = _counts()
        owner_share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=created["run"]["workflow_run"],
            selected_assets=[created["asset"].name],
        )["share"]
        owner_repeated = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=created["run"]["workflow_run"],
            selected_assets=[created["asset"].name],
        )["share"]
        self.assertEqual(owner_repeated["name"], owner_share["name"])
        _assert_counts_delta(self, before_owner, {"AI Tool Run Share": 1})

        frappe.set_user(self.editor)
        before_editor = _counts()
        editor_share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=created["run"]["workflow_run"],
            selected_assets=[created["other_asset"].name],
        )["share"]
        self.assertNotEqual(editor_share["name"], owner_share["name"])
        _assert_counts_delta(self, before_editor, {"AI Tool Run Share": 1})

        frappe.set_user("Guest")
        before_read = _counts()
        payload = frappe.call("slow_ai.api.public_tools.get_shared_run", share_token=owner_share["share_token"])
        _assert_counts_delta(self, before_read, {})

        self.assertEqual({row["name"] for row in payload["assets"]}, {created["asset"].name})
        self.assertEqual({row["name"] for row in payload["output_gallery"]["assets"]}, {created["asset"].name})
        grouped = {
            asset["name"]
            for group in payload["output_gallery"]["groups"]
            for asset in group.get("assets", [])
        }
        self.assertEqual(grouped, {created["asset"].name})
        self.assertNotIn("project", payload["run"])
        self.assertNotIn("project", payload["output_gallery"]["run"])
        self.assertNotIn("workflow", payload["output_gallery"]["run"])
        _assert_safe_payload(
            self,
            payload,
            created["project"].name,
            created["other_asset"].name,
            provider_job,
        )

        frappe.set_user(self.owner)
        before_disable = _counts()
        disabled = frappe.call("slow_ai.api.public_tools.disable_run_share", share_token=owner_share["share_token"])["share"]
        repeated_disable = frappe.call("slow_ai.api.public_tools.disable_run_share", share=owner_share["name"])["share"]
        self.assertEqual(disabled["status"], "DISABLED")
        self.assertEqual(repeated_disable["status"], "DISABLED")
        self.assertIsNone(repeated_disable["share_token"])
        _assert_counts_delta(self, before_disable, {})

        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.public_tools.get_shared_run", share_token=owner_share["share_token"])

    def test_share_mutation_denials_and_bad_asset_selection_are_side_effect_free(self):
        created = create_shareable_asset_run(self.owner, title="Share Token Denial Run")
        other = create_shareable_asset_run(self.owner, title="Share Token Other Run")
        active = create_text_tool_run(self.owner, title="Share Token Active Run")
        add_member(created["project"].name, self.viewer, "VIEWER")
        add_member(created["project"].name, self.billing, "BILLING")
        disabled_editor = add_member(created["project"].name, self.editor, "EDITOR")
        frappe.db.set_value("AI Project Member", disabled_editor.name, "status", "DISABLED")

        denied_cases = [
            (self.viewer, {"workflow_run": created["run"]["workflow_run"], "selected_assets": [created["asset"].name]}),
            (self.billing, {"workflow_run": created["run"]["workflow_run"], "selected_assets": [created["asset"].name]}),
            (self.editor, {"workflow_run": created["run"]["workflow_run"], "selected_assets": [created["asset"].name]}),
            (self.outsider, {"workflow_run": created["run"]["workflow_run"], "selected_assets": [created["asset"].name]}),
            ("Guest", {"workflow_run": created["run"]["workflow_run"], "selected_assets": [created["asset"].name]}),
            (self.owner, {"workflow_run": active["run"]["workflow_run"], "selected_assets": [created["asset"].name]}),
            (self.owner, {"workflow_run": created["run"]["workflow_run"], "selected_assets": []}),
            (self.owner, {"workflow_run": created["run"]["workflow_run"], "selected_assets": ["AI-ASSET-UNKNOWN"]}),
            (self.owner, {"workflow_run": created["run"]["workflow_run"], "selected_assets": [other["asset"].name]}),
        ]

        for user, kwargs in denied_cases:
            frappe.set_user(user)
            before = _counts()
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                frappe.call("slow_ai.api.public_tools.create_run_share", **kwargs)
            _assert_counts_delta(self, before, {})

        frappe.set_user(self.owner)
        share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=created["run"]["workflow_run"],
            selected_assets=[created["asset"].name],
        )["share"]
        for user in (self.viewer, self.billing, self.editor, self.outsider, "Guest"):
            frappe.set_user(user)
            before = _counts()
            with self.assertRaises(frappe.PermissionError):
                frappe.call("slow_ai.api.public_tools.disable_run_share", share_token=share["share_token"])
            _assert_counts_delta(self, before, {})

    def test_disabled_expired_invalid_malformed_and_unknown_tokens_reject_safely(self):
        created = create_shareable_asset_run(self.owner, title="Share Token Expiry Run")
        frappe.set_user(self.owner)
        active_share = frappe.call(
            "slow_ai.api.public_tools.create_run_share",
            workflow_run=created["run"]["workflow_run"],
            selected_assets=[created["asset"].name],
        )["share"]
        frappe.call("slow_ai.api.public_tools.disable_run_share", share_token=active_share["share_token"])
        expired = insert_doc(
            {
                "doctype": "AI Tool Run Share",
                "workflow_run": created["run"]["workflow_run"],
                "project": created["project"].name,
                "share_token": f"expired-{uuid4().hex}",
                "status": "ACTIVE",
                "selected_assets_json": json.dumps([created["asset"].name]),
                "expires_at": add_days(now_datetime(), -1),
            }
        )

        for token in (
            active_share["share_token"],
            expired.share_token,
            "unknown-share-token",
            "../../../etc/passwd",
            "",
            None,
        ):
            frappe.set_user("Guest")
            before = _counts()
            with self.assertRaises(frappe.PermissionError):
                frappe.call("slow_ai.api.public_tools.get_shared_run", share_token=token)
            _assert_counts_delta(self, before, {})

    def test_authenticated_gallery_is_project_scoped_safe_and_shared_page_source_is_guest_only(self):
        created = create_shareable_asset_run(self.owner, title="Share Token Gallery Run")
        _add_unsafe_provider_job(created)
        add_member(created["project"].name, self.viewer, "VIEWER")

        frappe.set_user(self.viewer)
        before_gallery = _counts()
        gallery = frappe.call(
            "slow_ai.api.public_tools.get_run_output_gallery",
            workflow_run=created["run"]["workflow_run"],
        )
        _assert_counts_delta(self, before_gallery, {})
        self.assertIn(created["asset"].name, {row["name"] for row in gallery["assets"]})
        self.assertIn(created["other_asset"].name, {row["name"] for row in gallery["assets"]})
        _assert_safe_payload(self, gallery, fragments=AUTHENTICATED_UNSAFE_FRAGMENTS)

        frappe.set_user(self.outsider)
        before_denied = _counts()
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.public_tools.get_run_output_gallery",
                workflow_run=created["run"]["workflow_run"],
            )
        _assert_counts_delta(self, before_denied, {})

        source = (frappe.get_app_path("slow_ai") + "/www/slow-ai/shared.html")
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("slow_ai.api.public_tools.get_shared_run", text)
        for method in FORBIDDEN_SHARED_PAGE_METHODS:
            self.assertNotIn(method, text)
        for fragment in (
            "frappe.db",
            "frappe.enqueue",
            "api.wavespeed.ai",
            "api.replicate.com",
            "request_json",
            "response_json",
            "raw_error_json",
            "provider_account",
        ):
            self.assertNotIn(fragment, text)

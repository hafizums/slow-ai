import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.tests.integration.test_project_membership import create_project
from slow_ai.tests.integration.test_project_membership import ensure_user


SIDE_EFFECT_DOCTYPES = (
    "AI Provider Account",
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
    "AI Provider Account": ["name", "provider", "account_label", "project", "user", "status", "is_default", "modified"],
    "AI Workflow": ["name", "project", "status", "modified"],
    "AI Workflow Run": ["name", "status", "modified"],
    "AI Node Run": ["name", "status", "provider_job", "modified"],
    "AI Provider Job": ["name", "provider", "provider_account", "status", "modified"],
    "AI Asset": ["name", "project", "source_provider_job", "modified"],
    "AI Credit Ledger": ["name", "project", "ledger_type", "amount_usd", "modified"],
    "AI Tool Run Share": ["name", "workflow_run", "status", "modified"],
}

UNSAFE_FRAGMENTS = (
    "provider-access-secret",
    "sk_provider_access_should_not_leak",
    "api_key_secret",
    "api_key",
    "Authorization",
    "Bearer",
    "request_json",
    "response_json",
    "raw_error_json",
    "draft_nodes_json",
    "draft_edges_json",
    "https://api.wavespeed.ai",
    "https://api.replicate.com",
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in SIDE_EFFECT_DOCTYPES}


def _snapshot() -> dict[str, list[dict]]:
    rows = {}
    for doctype, fields in MUTATION_SNAPSHOT_FIELDS.items():
        rows[doctype] = [dict(row) for row in frappe.get_all(doctype, fields=fields, order_by="name asc")]
    return json.loads(json.dumps(rows, default=str))


def _assert_no_side_effects(testcase: FrappeTestCase, before_counts: dict[str, int], before_snapshot: dict[str, list[dict]]):
    testcase.assertEqual(_counts(), before_counts)
    testcase.assertEqual(_snapshot(), before_snapshot)


def _assert_counts_delta(testcase: FrappeTestCase, before: dict[str, int], expected_delta: dict[str, int]):
    after = _counts()
    for doctype in SIDE_EFFECT_DOCTYPES:
        testcase.assertEqual(after[doctype], before[doctype] + expected_delta.get(doctype, 0), doctype)


def _assert_safe_payload(testcase: FrappeTestCase, payload):
    encoded = json.dumps(payload, default=str)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


def _assert_safe_exception(testcase: FrappeTestCase, exc: BaseException):
    encoded = str(exc)
    for fragment in UNSAFE_FRAGMENTS:
        testcase.assertNotIn(fragment, encoded, fragment)


def _insert_provider_account(provider: str, project: str, *, user: str | None = None, is_default: int = 0, owner: str | None = None):
    previous_user = frappe.session.user
    if owner:
        frappe.set_user(owner)
    try:
        return frappe.get_doc(
            {
                "doctype": "AI Provider Account",
                "provider": provider,
                "account_label": _unique("Provider Access Account"),
                "project": project,
                "user": user,
                "api_key_secret": "provider-access-secret",
                "is_default": is_default,
                "status": "ACTIVE",
            }
        ).insert(ignore_permissions=True)
    finally:
        frappe.set_user(previous_user)


class TestProviderAccountAccessMatrix(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"provider-access-owner-{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"provider-access-editor-{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"provider-access-viewer-{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"provider-access-billing-{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"provider-access-outsider-{uuid4().hex[:8]}@example.test")
        self.project = create_project(self.owner)
        self.provider = _unique("provider-access")
        self._add_member(self.editor, "EDITOR")
        self._add_member(self.viewer, "VIEWER")
        self._add_member(self.billing, "BILLING")

    def tearDown(self):
        frappe.set_user("Administrator")

    def _add_member(self, user: str, role: str):
        frappe.set_user(self.owner)
        return frappe.call("slow_ai.api.projects.add_member", project=self.project.name, user=user, role=role)["member"]

    def _create_account_api(self, user: str, *, provider: str | None = None, label: str | None = None, is_default: int = 0):
        secret = f"sk_provider_access_should_not_leak_{uuid4().hex}"
        frappe.set_user(user)
        return frappe.call(
            "slow_ai.api.provider_accounts.create_account",
            provider=provider or self.provider,
            account_label=label or _unique("Provider Access API"),
            api_key=secret,
            project=self.project.name,
            is_default=is_default,
            rate_limit={"max_active_provider_jobs": 2, "Authorization": "Bearer should-not-leak"},
        )

    def test_owner_billing_and_system_manager_can_manage_project_provider_accounts_safely(self):
        for user in (self.owner, self.billing, "Administrator"):
            provider = _unique("provider-access-allowed")
            before = _counts()
            created = self._create_account_api(user, provider=provider, is_default=1)
            listed = frappe.call(
                "slow_ai.api.provider_accounts.list_accounts",
                provider=provider,
                project=self.project.name,
                include_disabled=1,
            )
            fetched = frappe.call("slow_ai.api.provider_accounts.get_account", account=created["account"]["name"])

            _assert_counts_delta(self, before, {"AI Provider Account": 1})
            _assert_safe_payload(self, {"created": created, "listed": listed, "fetched": fetched})
            self.assertEqual(created["account"]["project"], self.project.name)
            self.assertEqual(fetched["account"]["provider"], provider)
            self.assertNotIn("rate_limit_json", json.dumps(fetched, default=str))

    def test_editor_viewer_nonmember_and_guest_provider_account_actions_are_rejected_without_side_effects(self):
        account = _insert_provider_account(self.provider, self.project.name, is_default=1)
        for user in (self.editor, self.viewer, self.outsider, "Guest"):
            before_counts = _counts()
            before_snapshot = _snapshot()
            frappe.set_user(user)
            for method, kwargs in (
                (
                    "slow_ai.api.provider_accounts.create_account",
                    {
                        "provider": self.provider,
                        "account_label": _unique("Denied Provider Account"),
                        "api_key": "sk_provider_access_should_not_leak",
                        "project": self.project.name,
                    },
                ),
                ("slow_ai.api.provider_accounts.list_accounts", {"provider": self.provider, "project": self.project.name}),
                ("slow_ai.api.provider_accounts.get_account", {"account": account.name}),
                ("slow_ai.api.provider_accounts.set_default", {"account": account.name}),
                ("slow_ai.api.provider_accounts.disable_account", {"account": account.name}),
            ):
                with self.assertRaises(frappe.PermissionError) as exc:
                    frappe.call(method, **kwargs)
                _assert_safe_exception(self, exc.exception)
            frappe.set_user("Administrator")
            _assert_no_side_effects(self, before_counts, before_snapshot)

    def test_set_default_and_disable_mutate_only_intended_provider_account_fields(self):
        first = _insert_provider_account(self.provider, self.project.name, is_default=1)
        second = _insert_provider_account(self.provider, self.project.name, is_default=0)
        other_project = create_project(self.owner)
        other_scope = _insert_provider_account(self.provider, other_project.name, is_default=1)
        before_default = _counts()

        frappe.set_user(self.owner)
        defaulted = frappe.call("slow_ai.api.provider_accounts.set_default", account=second.name)

        _assert_counts_delta(self, before_default, {})
        _assert_safe_payload(self, defaulted)
        first.reload()
        second.reload()
        other_scope.reload()
        self.assertEqual(first.is_default, 0)
        self.assertEqual(second.is_default, 1)
        self.assertEqual(second.status, "ACTIVE")
        self.assertEqual(other_scope.is_default, 1)

        before_disable = _counts()
        disabled = frappe.call("slow_ai.api.provider_accounts.disable_account", account=second.name)

        _assert_counts_delta(self, before_disable, {})
        _assert_safe_payload(self, disabled)
        second.reload()
        self.assertEqual(second.status, "DISABLED")
        self.assertEqual(second.is_default, 0)
        first.reload()
        self.assertEqual(first.status, "ACTIVE")

    def test_disabled_members_and_role_changes_immediately_affect_provider_account_access(self):
        member = frappe.db.get_value("AI Project Member", {"project": self.project.name, "user": self.viewer}, "name")
        account = _insert_provider_account(self.provider, self.project.name, user=self.viewer, owner=self.viewer)

        before_denied = _counts()
        before_denied_snapshot = _snapshot()
        frappe.set_user(self.viewer)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.provider_accounts.get_account", account=account.name)
        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_denied, before_denied_snapshot)

        frappe.set_user(self.owner)
        frappe.call("slow_ai.api.projects.update_member_role", member=member, role="BILLING")
        frappe.set_user(self.viewer)
        fetched = frappe.call("slow_ai.api.provider_accounts.get_account", account=account.name)
        _assert_safe_payload(self, fetched)
        self.assertEqual(fetched["account"]["name"], account.name)

        frappe.set_user(self.owner)
        frappe.call("slow_ai.api.projects.disable_member", member=member)
        before_disabled = _counts()
        before_disabled_snapshot = _snapshot()
        frappe.set_user(self.viewer)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.provider_accounts.get_account", account=account.name)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.provider_accounts.set_default", account=account.name)
        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_disabled, before_disabled_snapshot)

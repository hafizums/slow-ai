import json
from decimal import Decimal
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.domain.exceptions import RunPreflightError
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
    "AI Provider Account": ["name", "provider", "project", "status", "is_default", "modified"],
    "AI Workflow": ["name", "project", "status", "modified"],
    "AI Workflow Run": ["name", "workflow", "status", "modified"],
    "AI Node Run": ["name", "workflow_run", "status", "provider_job", "modified"],
    "AI Provider Job": ["name", "provider", "provider_account", "status", "modified"],
    "AI Asset": ["name", "project", "source_provider_job", "modified"],
    "AI Credit Ledger": [
        "name",
        "project",
        "workflow_run",
        "node_run",
        "provider_job",
        "ledger_type",
        "amount_usd",
        "modified",
    ],
    "AI Tool Run Share": ["name", "workflow_run", "status", "modified"],
}

UNSAFE_FRAGMENTS = (
    "billing-access-provider-account",
    "billing-access-secret",
    "sk_billing_access_should_not_leak",
    "provider_account",
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


def _insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def _create_model(provider: str, amount_usd: str = "0.10"):
    return _insert_doc(
        {
            "doctype": "AI Model",
            "model_id": _unique(f"{provider}/model"),
            "model_slug": _unique(f"{provider}-slug"),
            "model_name": "Billing Access Test Model",
            "provider": provider,
            "status": "ENABLED",
            "node_type": "provider_text_to_image",
            "category": "provider",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "amount_usd": amount_usd}),
        }
    )


def _create_provider_account(provider: str, project: str):
    return _insert_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider,
            "account_label": _unique("billing-access-provider-account"),
            "project": project,
            "api_key_secret": "billing-access-secret",
            "is_default": 1,
            "status": "ACTIVE",
        }
    )


def _create_provider_workflow(project: str, provider: str, model: str):
    return _insert_doc(
        {
            "doctype": "AI Workflow",
            "project": project,
            "title": _unique("Billing Access Provider Workflow"),
            "status": "DRAFT",
            "draft_nodes_json": json.dumps(
                [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "Billing access prompt"}},
                    {
                        "id": "provider_1",
                        "type": "provider_text_to_image",
                        "config": {"provider": provider, "model": model},
                    },
                    {"id": "output_1", "type": "export_output", "config": {}},
                ]
            ),
            "draft_edges_json": json.dumps(
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
                ]
            ),
            "layout_json": "{}",
        }
    )


class TestBillingTopupLedgerAccessMatrix(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.owner = ensure_user(f"billing-access-owner-{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"billing-access-editor-{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"billing-access-viewer-{uuid4().hex[:8]}@example.test")
        self.billing = ensure_user(f"billing-access-billing-{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"billing-access-outsider-{uuid4().hex[:8]}@example.test")
        self.project = create_project(self.owner)
        self._add_member(self.editor, "EDITOR")
        self._add_member(self.viewer, "VIEWER")
        self.billing_member = self._add_member(self.billing, "BILLING")

    def tearDown(self):
        frappe.set_user("Administrator")

    def _add_member(self, user: str, role: str):
        frappe.set_user(self.owner)
        return frappe.call("slow_ai.api.projects.add_member", project=self.project.name, user=user, role=role)["member"]

    def _top_up(self, user: str, amount: str = "1.25"):
        frappe.set_user(user)
        return frappe.call(
            "slow_ai.api.billing.create_top_up",
            project=self.project.name,
            amount_usd=amount,
            description="Billing access matrix top-up",
            reference_doctype="AI Project",
            reference_name=self.project.name,
        )

    def test_owner_billing_and_system_manager_can_top_up_and_read_safe_ledger_payloads(self):
        for user in (self.owner, self.billing, "Administrator"):
            before = _counts()
            top_up = self._top_up(user, "1.25")
            balance = frappe.call("slow_ai.api.billing.get_balance", project=self.project.name)
            ledger = frappe.call("slow_ai.api.billing.get_ledger", project=self.project.name, limit=10)

            _assert_counts_delta(self, before, {"AI Credit Ledger": 1})
            _assert_safe_payload(self, {"top_up": top_up, "balance": balance, "ledger": ledger})
            self.assertEqual(top_up["ledger"]["ledger_type"], "CREDIT")
            self.assertEqual(Decimal(top_up["ledger"]["amount_usd"]), Decimal("1.25"))
            self.assertIn(top_up["ledger"]["name"], {row["name"] for row in ledger["ledger"]})

    def test_editor_viewer_nonmember_and_guest_billing_actions_are_rejected_without_side_effects(self):
        for user in (self.editor, self.viewer, self.outsider, "Guest"):
            before_counts = _counts()
            before_snapshot = _snapshot()
            frappe.set_user(user)
            for method, kwargs in (
                (
                    "slow_ai.api.billing.create_top_up",
                    {
                        "project": self.project.name,
                        "amount_usd": "1.00",
                        "description": "Denied billing top-up",
                    },
                ),
                ("slow_ai.api.billing.get_balance", {"project": self.project.name}),
                ("slow_ai.api.billing.get_ledger", {"project": self.project.name}),
            ):
                with self.assertRaises(frappe.PermissionError) as exc:
                    frappe.call(method, **kwargs)
                _assert_safe_exception(self, exc.exception)
            frappe.set_user("Administrator")
            _assert_no_side_effects(self, before_counts, before_snapshot)

    def test_get_balance_and_get_ledger_are_read_only_for_billing_roles(self):
        self._top_up(self.owner, "2.00")
        for user in (self.owner, self.billing, "Administrator"):
            before_counts = _counts()
            before_snapshot = _snapshot()
            frappe.set_user(user)
            balance = frappe.call("slow_ai.api.billing.get_balance", project=self.project.name)
            ledger = frappe.call("slow_ai.api.billing.get_ledger", project=self.project.name)

            _assert_safe_payload(self, {"balance": balance, "ledger": ledger})
            self.assertGreaterEqual(Decimal(balance["balance_usd"]), Decimal("2.00"))
            frappe.set_user("Administrator")
            _assert_no_side_effects(self, before_counts, before_snapshot)

    def test_disabled_billing_member_loses_billing_access(self):
        frappe.set_user(self.billing)
        balance = frappe.call("slow_ai.api.billing.get_balance", project=self.project.name)
        _assert_safe_payload(self, balance)

        frappe.set_user(self.owner)
        frappe.call("slow_ai.api.projects.disable_member", member=self.billing_member["name"])
        before_counts = _counts()
        before_snapshot = _snapshot()

        frappe.set_user(self.billing)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.billing.get_balance", project=self.project.name)
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.billing.create_top_up", project=self.project.name, amount_usd="1.00")
        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_counts, before_snapshot)

    def test_balance_preflight_rejects_before_side_effects_then_top_up_allows_start(self):
        provider = _unique("billing-access-provider")
        model = _create_model(provider, "0.10")
        _create_provider_account(provider, self.project.name)
        workflow = _create_provider_workflow(self.project.name, provider, model.name)
        self._top_up(self.owner, "0.04")

        before_reject_counts = _counts()
        before_reject_snapshot = _snapshot()
        frappe.set_user(self.owner)
        with self.assertRaises(RunPreflightError) as exc:
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)
        self.assertIn("exceeds available project credit balance", str(exc.exception))
        frappe.set_user("Administrator")
        _assert_no_side_effects(self, before_reject_counts, before_reject_snapshot)

        self._top_up(self.billing, "0.20")
        before_start = _counts()
        frappe.set_user(self.owner)
        started = frappe.call("slow_ai.api.runs.start_run", workflow=workflow.name)
        _assert_safe_payload(self, started)
        self.assertTrue(started["workflow_version"])
        self.assertTrue(started["workflow_run"])
        self.assertEqual(len(started["node_runs"]), 3)
        _assert_counts_delta(
            self,
            before_start,
            {
                "AI Workflow Version": 1,
                "AI Workflow Run": 1,
                "AI Node Run": 3,
                "AI Credit Ledger": 1,
            },
        )
        reservation = frappe.get_doc(
            "AI Credit Ledger",
            frappe.db.get_value("AI Credit Ledger", {"workflow_run": started["workflow_run"], "ledger_type": "RESERVE"}),
        )
        self.assertEqual(Decimal(str(reservation.amount_usd)), Decimal("0.10"))

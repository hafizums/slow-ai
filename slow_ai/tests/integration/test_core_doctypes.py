import json
from pathlib import Path
from uuid import uuid4

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase

from slow_ai.doctype.contracts import PERMANENT_DOCTYPES


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict) -> Document:
    return frappe.get_doc(data).insert(ignore_permissions=True)


class TestCoreDocTypes(FrappeTestCase):
    def create_document_chain(self):
        project = insert_doc(
            {
                "doctype": "AI Project",
                "project_name": unique("Project"),
                "status": "Open",
            }
        )
        model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": unique("wavespeed/model"),
                "model_name": "WaveSpeed Test Model",
                "provider": "wavespeed",
                "status": "ENABLED",
                "modality": "TEXT_TO_IMAGE",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": 0.01}),
            }
        )
        provider_account = insert_doc(
            {
                "doctype": "AI Provider Account",
                "provider": "wavespeed",
                "account_label": unique("WaveSpeed Test"),
                "api_key_secret": "test-secret",
                "is_default": 1,
                "status": "ACTIVE",
                "rate_limit_json": json.dumps({"rpm": 60}),
            }
        )
        workflow = insert_doc(
            {
                "doctype": "AI Workflow",
                "title": unique("Workflow"),
                "project": project.name,
                "status": "DRAFT",
                "draft_nodes_json": json.dumps(
                    [{"id": "prompt_1", "type": "text_prompt", "config": {"text": "A test"}}]
                ),
                "draft_edges_json": json.dumps([]),
                "layout_json": json.dumps({"nodes": []}),
            }
        )
        version = insert_doc(
            {
                "doctype": "AI Workflow Version",
                "workflow": workflow.name,
                "version_no": 1,
                "snapshot_hash": unique("snapshot"),
                "nodes_json": workflow.draft_nodes_json,
                "edges_json": workflow.draft_edges_json,
                "layout_json": workflow.layout_json,
            }
        )
        workflow_run = insert_doc(
            {
                "doctype": "AI Workflow Run",
                "project": project.name,
                "workflow": workflow.name,
                "workflow_version": version.name,
                "status": "QUEUED",
            }
        )
        node_run = insert_doc(
            {
                "doctype": "AI Node Run",
                "workflow_run": workflow_run.name,
                "node_id": "prompt_1",
                "node_type": "text_prompt",
                "status": "PENDING",
                "attempt_no": 1,
                "input_json": json.dumps({}),
                "config_json": json.dumps({"text": "A test"}),
            }
        )
        provider_job = insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run.name,
                "provider": "wavespeed",
                "provider_account": provider_account.name,
                "model": model.name,
                "status": "QUEUED",
                "idempotency_key": unique("idempotency"),
                "request_json": json.dumps({"prompt": "A test"}),
            }
        )
        asset = insert_doc(
            {
                "doctype": "AI Asset",
                "project": project.name,
                "asset_type": "IMAGE",
                "url": "https://example.invalid/output.png",
                "mime_type": "image/png",
                "source_workflow_run": workflow_run.name,
                "source_node_run": node_run.name,
                "source_provider_job": provider_job.name,
                "metadata_json": json.dumps({"source": "integration-test"}),
            }
        )
        ledger = insert_doc(
            {
                "doctype": "AI Credit Ledger",
                "project": project.name,
                "workflow_run": workflow_run.name,
                "node_run": node_run.name,
                "provider_job": provider_job.name,
                "ledger_type": "DEBIT",
                "amount_usd": 0.01,
                "currency": "USD",
                "description": "Integration test debit",
            }
        )
        template = insert_doc(
            {
                "doctype": "AI Workflow Template",
                "template_name": unique("Template"),
                "status": "DRAFT",
                "category": "Test",
                "preview_asset": asset.name,
                "nodes_json": workflow.draft_nodes_json,
                "edges_json": workflow.draft_edges_json,
                "layout_json": workflow.layout_json,
            }
        )

        return {
            "project": project,
            "model": model,
            "provider_account": provider_account,
            "workflow": workflow,
            "version": version,
            "workflow_run": workflow_run,
            "node_run": node_run,
            "provider_job": provider_job,
            "asset": asset,
            "ledger": ledger,
            "template": template,
        }

    def test_platform_kernel_creates_real_documents(self):
        docs = self.create_document_chain()

        for doctype in PERMANENT_DOCTYPES:
            self.assertTrue(frappe.db.exists("DocType", doctype), doctype)

        for doc in docs.values():
            self.assertTrue(frappe.db.exists(doc.doctype, doc.name), doc.doctype)

    def test_workflow_version_is_immutable_after_insert(self):
        version = self.create_document_chain()["version"]
        version.snapshot_hash = unique("changed")

        with self.assertRaises(frappe.ValidationError):
            version.save(ignore_permissions=True)

    def test_credit_ledger_is_append_only(self):
        ledger = self.create_document_chain()["ledger"]
        ledger.amount_usd = 0.02

        with self.assertRaises(frappe.ValidationError):
            ledger.save(ignore_permissions=True)

    def test_provider_account_secret_uses_password_field(self):
        field = frappe.get_meta("AI Provider Account").get_field("api_key_secret")

        self.assertEqual(field.fieldtype, "Password")

    def test_doctype_controllers_stay_persistence_only(self):
        for doctype in PERMANENT_DOCTYPES:
            meta = frappe.get_meta(doctype)
            self.assertEqual(meta.module, "Slow Ai")

        controller_paths = [
            "slow_ai/doctype/ai_project/ai_project.py",
            "slow_ai/doctype/ai_workflow/ai_workflow.py",
            "slow_ai/doctype/ai_workflow_version/ai_workflow_version.py",
            "slow_ai/doctype/ai_workflow_run/ai_workflow_run.py",
            "slow_ai/doctype/ai_node_run/ai_node_run.py",
            "slow_ai/doctype/ai_asset/ai_asset.py",
            "slow_ai/doctype/ai_provider_job/ai_provider_job.py",
            "slow_ai/doctype/ai_model/ai_model.py",
            "slow_ai/doctype/ai_provider_account/ai_provider_account.py",
            "slow_ai/doctype/ai_credit_ledger/ai_credit_ledger.py",
            "slow_ai/doctype/ai_workflow_template/ai_workflow_template.py",
        ]
        forbidden = ("providers.", "engine.", "node_registry.", "frappe.enqueue")
        for path in controller_paths:
            source = Path(frappe.get_app_path("slow_ai", path)).read_text()
            self.assertFalse(any(token in source for token in forbidden), path)

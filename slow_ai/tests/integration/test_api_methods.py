import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


def create_project():
    return insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("API Project"),
            "status": "Open",
        }
    )


def workflow_nodes(text: str = "A product photo"):
    return [
        {"id": "prompt_1", "type": "text_prompt", "config": {"text": text}},
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


class TestAPIMethods(FrappeTestCase):
    def test_save_and_get_workflow_api_persists_draft(self):
        project = create_project()

        saved = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            project=project.name,
            title="API Workflow",
            nodes=json.dumps(workflow_nodes()),
            edges=json.dumps(workflow_edges()),
            layout=json.dumps({"nodes": [{"id": "prompt_1", "x": 10, "y": 20}]}),
        )
        loaded = frappe.call("slow_ai.api.workflows.get_workflow", workflow=saved["name"])

        self.assertTrue(frappe.db.exists("AI Workflow", saved["name"]))
        self.assertEqual(loaded["title"], "API Workflow")
        self.assertEqual(loaded["project"], project.name)
        self.assertEqual(loaded["nodes"][0]["type"], "text_prompt")
        self.assertEqual(loaded["layout"]["nodes"][0]["id"], "prompt_1")

    def test_start_run_api_creates_records_and_enqueues_without_inline_execution(self):
        project = create_project()
        workflow = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            project=project.name,
            title="API Runnable Workflow",
            nodes=workflow_nodes(),
            edges=workflow_edges(),
            layout={},
        )

        result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])
        status = frappe.call("slow_ai.api.runs.get_run_status", workflow_run=result["workflow_run"])
        queue_status = frappe.call("slow_ai.api.queue.get_queue_status")

        self.assertTrue(result["queue_job_id"].startswith("slow_ai:workflow_run:"))
        self.assertTrue(frappe.db.exists("AI Workflow Version", result["workflow_version"]))
        self.assertTrue(frappe.db.exists("AI Workflow Run", result["workflow_run"]))
        self.assertEqual(status["status"], "QUEUED")
        self.assertEqual({row["status"] for row in status["node_runs"]}, {"PENDING"})
        self.assertIn(result["workflow_run"], {row["name"] for row in queue_status["queued"]})

    def test_get_history_api_returns_node_provider_asset_and_ledger_records(self):
        project = create_project()
        workflow = frappe.call(
            "slow_ai.api.workflows.save_workflow",
            project=project.name,
            title="API History Workflow",
            nodes=workflow_nodes(),
            edges=workflow_edges(),
            layout={},
        )
        result = frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])
        node_run_name = frappe.db.get_value(
            "AI Node Run",
            {"workflow_run": result["workflow_run"], "node_id": "prompt_1"},
            "name",
        )
        model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": unique("history/model"),
                "model_name": "History Test Model",
                "provider": "history_provider",
                "status": "ENABLED",
                "modality": "TEXT_TO_IMAGE",
            }
        )
        provider_job = insert_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": node_run_name,
                "provider": "history_provider",
                "model": model.name,
                "status": "SUCCEEDED",
                "idempotency_key": unique("history-job"),
                "request_json": json.dumps({"prompt": "A product photo"}),
                "response_json": json.dumps({"status": "completed"}),
            }
        )
        asset = insert_doc(
            {
                "doctype": "AI Asset",
                "project": project.name,
                "asset_type": "IMAGE",
                "url": "https://example.invalid/history.png",
                "mime_type": "image/png",
                "source_workflow_run": result["workflow_run"],
                "source_node_run": node_run_name,
                "source_provider_job": provider_job.name,
                "metadata_json": json.dumps({"source": "api-history-test"}),
            }
        )
        ledger = insert_doc(
            {
                "doctype": "AI Credit Ledger",
                "project": project.name,
                "workflow_run": result["workflow_run"],
                "node_run": node_run_name,
                "provider_job": provider_job.name,
                "ledger_type": "DEBIT",
                "amount_usd": 0.03,
                "currency": "USD",
                "description": "API history test",
            }
        )

        history = frappe.call("slow_ai.api.runs.get_history", workflow_run=result["workflow_run"])

        self.assertEqual(history["run"]["workflow_run"], result["workflow_run"])
        self.assertIn(provider_job.name, {row["name"] for row in history["provider_jobs"]})
        self.assertIn(asset.name, {row["name"] for row in history["assets"]})
        self.assertIn(ledger.name, {row["name"] for row in history["ledger"]})
        self.assertEqual(history["assets"][0]["metadata"]["source"], "api-history-test")

    def test_upload_and_view_asset_api_create_real_asset(self):
        project = create_project()

        uploaded = frappe.call(
            "slow_ai.api.assets.upload",
            project=project.name,
            asset_type="IMAGE",
            url="https://example.invalid/upload.png",
            mime_type="image/png",
            metadata=json.dumps({"origin": "api-test"}),
        )
        viewed = frappe.call("slow_ai.api.assets.view", asset=uploaded["name"])

        self.assertTrue(frappe.db.exists("AI Asset", uploaded["name"]))
        self.assertEqual(viewed["project"], project.name)
        self.assertEqual(viewed["asset_type"], "IMAGE")
        self.assertEqual(viewed["url"], "https://example.invalid/upload.png")
        self.assertEqual(viewed["metadata"]["origin"], "api-test")
        self.assertIn("created", viewed)
        self.assertIn("modified", viewed)

    def test_get_object_info_api_remains_metadata_only(self):
        object_info = frappe.call("slow_ai.api.nodes.get_object_info")

        self.assertIn("provider_text_to_image", object_info["nodes"])
        self.assertEqual(
            object_info["nodes"]["provider_text_to_image"]["input_schema"]["prompt"]["type"],
            "TEXT",
        )

    def test_get_model_metadata_api_returns_public_pricing_metadata(self):
        priced_model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": unique("api/priced-model"),
                "model_name": "API Priced Model",
                "provider": "wavespeed",
                "status": "ENABLED",
                "modality": "TEXT_TO_IMAGE",
                "pricing_json": json.dumps({"unit": "run", "amount_usd": "0.25"}),
            }
        )
        unpriced_model = insert_doc(
            {
                "doctype": "AI Model",
                "model_id": unique("api/unpriced-model"),
                "model_name": "API Unpriced Model",
                "provider": "wavespeed",
                "status": "ENABLED",
                "modality": "TEXT_TO_IMAGE",
            }
        )

        metadata = frappe.call(
            "slow_ai.api.models.get_model_metadata",
            model_ids=json.dumps([priced_model.name, unpriced_model.name]),
        )

        self.assertEqual(metadata["models"][priced_model.name]["estimated_cost_usd"], "0.25")
        self.assertTrue(metadata["models"][priced_model.name]["pricing_known"])
        self.assertFalse(metadata["models"][unpriced_model.name]["pricing_known"])
        self.assertNotIn("pricing_json", metadata["models"][priced_model.name])

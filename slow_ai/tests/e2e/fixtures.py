"""Real persisted fixtures for Slow AI browser E2E tests."""

from __future__ import annotations

import json
from uuid import uuid4

import frappe
from frappe.utils import now_datetime
from frappe.utils.password import update_password


E2E_USER = "slow.ai.e2e@example.test"
E2E_PASSWORD = "SlowAiE2E!2345"


def setup_canvas_e2e() -> dict:
    """Create real Frappe documents used by the browser test suite."""

    user = _ensure_user()
    project = _create_project()
    placeholder_asset = frappe.call(
        "slow_ai.api.assets.upload",
        project=project.name,
        asset_type="IMAGE",
        url="https://example.invalid/e2e-placeholder.png",
        mime_type="image/png",
        metadata=json.dumps({"origin": "browser-e2e-placeholder"}),
    )
    selected_asset = frappe.call(
        "slow_ai.api.assets.upload",
        project=project.name,
        asset_type="IMAGE",
        url="https://example.invalid/e2e-selected.png",
        mime_type="image/png",
        metadata=json.dumps({"origin": "browser-e2e-selected"}),
    )
    tool_template = _create_tool_template()
    upload_template = _create_upload_template(placeholder_asset["name"])
    asset_run = _create_history_asset_run(project.name)
    frappe.db.commit()
    return {
        "user": user,
        "password": E2E_PASSWORD,
        "project": project.name,
        "canvas_title": f"Browser E2E Canvas {uuid4().hex[:8]}",
        "tool_template": tool_template["name"],
        "tool_template_label": tool_template["template_name"],
        "tool_prompt": f"Browser Tool Prompt {uuid4().hex[:8]}",
        "upload_template": upload_template["name"],
        "upload_template_label": upload_template["template_name"],
        "selected_asset": selected_asset["name"],
        "upload_url": f"https://example.invalid/e2e-created-{uuid4().hex[:8]}.png",
        "provider_account_provider": f"browser-e2e-provider-{uuid4().hex[:8]}",
        "provider_account_label": f"Browser E2E Provider Account {uuid4().hex[:8]}",
        "provider_account_secret": f"browser-e2e-secret-{uuid4().hex[:8]}",
        "asset_workflow_run": asset_run["workflow_run"],
        "history_asset": asset_run["asset"],
    }


def _ensure_user() -> str:
    if frappe.db.exists("User", E2E_USER):
        user = frappe.get_doc("User", E2E_USER)
        user.enabled = 1
        user.user_type = "System User"
        user.save(ignore_permissions=True)
    else:
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": E2E_USER,
                "first_name": "Slow AI",
                "last_name": "E2E",
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
                "roles": [{"role": "System Manager"}],
            }
        ).insert(ignore_permissions=True)
    existing_roles = {row.role for row in user.get("roles", [])}
    if "System Manager" not in existing_roles:
        user.append("roles", {"role": "System Manager"})
        user.save(ignore_permissions=True)
    update_password(E2E_USER, E2E_PASSWORD)
    return E2E_USER


def _create_project():
    return frappe.get_doc(
        {
            "doctype": "AI Project",
            "project_name": _unique("Browser E2E Project"),
            "status": "Open",
        }
    ).insert(ignore_permissions=True)


def _create_tool_template() -> dict:
    return frappe.call(
        "slow_ai.api.templates.save_template",
        template_name=_unique("Browser E2E Text Tool"),
        status="PUBLISHED",
        category="Browser E2E",
        description="Browser E2E text prompt Tool Mode template",
        nodes=json.dumps(
            [
                {
                    "id": "prompt_1",
                    "type": "text_prompt",
                    "label": "Prompt",
                    "position": {"x": 96, "y": 128},
                    "config": {"text": "Template prompt"},
                },
                {
                    "id": "tool_output_1",
                    "type": "tool_output",
                    "label": "Tool Output",
                    "position": {"x": 376, "y": 128},
                    "config": {
                        "output_name": "answer",
                        "description": "Primary tool output",
                        "schema": {"type": "string"},
                    },
                },
            ]
        ),
        edges=json.dumps(
            [
                {
                    "id": "edge_1",
                    "source": "prompt_1",
                    "source_port": "text",
                    "target": "tool_output_1",
                    "target_port": "text",
                }
            ]
        ),
        layout=json.dumps({"nodes": [{"id": "prompt_1", "x": 96, "y": 128}]}),
    )


def _create_upload_template(asset_name: str) -> dict:
    return frappe.call(
        "slow_ai.api.templates.save_template",
        template_name=_unique("Browser E2E Upload Tool"),
        status="PUBLISHED",
        category="Browser E2E",
        description="Browser E2E upload_asset Tool Mode template",
        nodes=json.dumps(
            [
                {
                    "id": "asset_1",
                    "type": "upload_asset",
                    "label": "Input Asset",
                    "position": {"x": 96, "y": 128},
                    "config": {"asset": asset_name, "asset_type": "IMAGE"},
                },
                {
                    "id": "tool_output_1",
                    "type": "tool_output",
                    "label": "Tool Output",
                    "position": {"x": 376, "y": 128},
                    "config": {
                        "output_name": "image",
                        "description": "Selected image asset",
                        "schema": {"type": "string"},
                    },
                },
            ]
        ),
        edges=json.dumps(
            [
                {
                    "id": "edge_1",
                    "source": "asset_1",
                    "source_port": "image",
                    "target": "tool_output_1",
                    "target_port": "image",
                }
            ]
        ),
        layout=json.dumps({"nodes": [{"id": "asset_1", "x": 96, "y": 128}]}),
    )


def _create_history_asset_run(project: str) -> dict:
    workflow = frappe.call(
        "slow_ai.api.workflows.save_workflow",
        project=project,
        title="Browser E2E Asset History",
        nodes=json.dumps(
            [
                {
                    "id": "prompt_1",
                    "type": "text_prompt",
                    "label": "Prompt",
                    "position": {"x": 96, "y": 128},
                    "config": {"text": "Asset history prompt"},
                },
                {
                    "id": "tool_output_1",
                    "type": "tool_output",
                    "label": "Tool Output",
                    "position": {"x": 376, "y": 128},
                    "config": {
                        "output_name": "answer",
                        "description": "Asset history output",
                        "schema": {"type": "string"},
                    },
                },
            ]
        ),
        edges=json.dumps(
            [
                {
                    "id": "edge_1",
                    "source": "prompt_1",
                    "source_port": "text",
                    "target": "tool_output_1",
                    "target_port": "text",
                }
            ]
        ),
        layout=json.dumps({"nodes": [{"id": "tool_output_1", "x": 376, "y": 128}]}),
    )
    run = frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])
    node_run = frappe.db.get_value(
        "AI Node Run",
        {"workflow_run": run["workflow_run"], "node_id": "tool_output_1"},
        "name",
    )
    timestamp = now_datetime()
    frappe.db.set_value(
        "AI Workflow Run",
        run["workflow_run"],
        {"status": "SUCCEEDED", "started_at": timestamp, "completed_at": timestamp},
    )
    frappe.db.set_value(
        "AI Node Run",
        node_run,
        {
            "status": "SUCCEEDED",
            "started_at": timestamp,
            "completed_at": timestamp,
            "output_json": json.dumps({"text": "Asset history output"}),
        },
    )
    asset = frappe.get_doc(
        {
            "doctype": "AI Asset",
            "project": project,
            "asset_type": "IMAGE",
            "url": f"https://example.invalid/e2e-history-{uuid4().hex[:8]}.png",
            "mime_type": "image/png",
            "width": 320,
            "height": 240,
            "source_workflow_run": run["workflow_run"],
            "source_node_run": node_run,
            "metadata_json": json.dumps({"origin": "browser-e2e-history"}),
        }
    ).insert(ignore_permissions=True)
    return {"workflow_run": run["workflow_run"], "asset": asset.name}


def _unique(prefix: str) -> str:
    return f"{prefix} {uuid4().hex[:8]}"

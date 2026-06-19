"""Real persisted fixtures for Slow AI browser E2E tests."""

from __future__ import annotations

import json
from uuid import uuid4

import frappe
from frappe.utils import now_datetime
from frappe.utils.password import update_password


E2E_USER = "slow.ai.e2e@example.test"
E2E_PASSWORD = "SlowAiE2E!2345"
PUBLIC_TOOL_USER = "slow.ai.public.e2e@example.test"
PUBLIC_TOOL_PASSWORD = "SlowAiPublicE2E!2345"
PUBLIC_TOOL_EDITOR_USER = "slow.ai.public.editor.e2e@example.test"
PUBLIC_TOOL_EDITOR_PASSWORD = "SlowAiPublicEditorE2E!2345"
PUBLIC_TOOL_VIEWER_USER = "slow.ai.public.viewer.e2e@example.test"
PUBLIC_TOOL_VIEWER_PASSWORD = "SlowAiPublicViewerE2E!2345"


def setup_canvas_e2e() -> dict:
    """Create real Frappe documents used by the browser test suite."""

    user = _ensure_user()
    public_tool_user = _ensure_public_tool_user()
    public_tool_editor_user = _ensure_public_tool_member_user(PUBLIC_TOOL_EDITOR_USER, PUBLIC_TOOL_EDITOR_PASSWORD)
    public_tool_viewer_user = _ensure_public_tool_member_user(PUBLIC_TOOL_VIEWER_USER, PUBLIC_TOOL_VIEWER_PASSWORD)
    project = _create_project()
    public_tool_project = _create_project(owner=public_tool_user)
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
    public_tool_asset = frappe.call(
        "slow_ai.api.assets.upload",
        project=public_tool_project.name,
        asset_type="IMAGE",
        url="https://example.invalid/e2e-public-tool-selected.png",
        mime_type="image/png",
        metadata=json.dumps({"origin": "browser-e2e-public-tool-selected"}),
    )
    tool_template = _create_tool_template()
    upload_template = _create_upload_template(placeholder_asset["name"])
    public_tool_template = _create_tool_template(prefix="Browser E2E Public Text Tool")
    public_legacy_template = _create_legacy_tool_template(prefix="Browser E2E Public Legacy Text Tool")
    public_upload_template = _create_upload_template(
        public_tool_asset["name"],
        prefix="Browser E2E Public Upload Tool",
    )
    review_template = _create_tool_template(prefix="Browser E2E Review Draft", status="DRAFT")
    rejected_template = _create_tool_template(prefix="Browser E2E Rejected Tool", status="REJECTED")
    archived_template = _create_tool_template(prefix="Browser E2E Archived Tool", status="ARCHIVED")
    catalog_model = _create_catalog_model()
    asset_run = _create_history_asset_run(project.name)
    public_asset_run = _create_history_asset_run(public_tool_project.name)
    frappe.db.commit()
    return {
        "user": user,
        "password": E2E_PASSWORD,
        "public_tool_user": public_tool_user,
        "public_tool_password": PUBLIC_TOOL_PASSWORD,
        "public_tool_editor_user": public_tool_editor_user,
        "public_tool_editor_password": PUBLIC_TOOL_EDITOR_PASSWORD,
        "public_tool_viewer_user": public_tool_viewer_user,
        "public_tool_viewer_password": PUBLIC_TOOL_VIEWER_PASSWORD,
        "public_tool_project": public_tool_project.name,
        "public_tool_template": public_tool_template["name"],
        "public_tool_template_label": public_tool_template["template_name"],
        "public_legacy_template": public_legacy_template["name"],
        "public_legacy_template_label": public_legacy_template["template_name"],
        "public_legacy_prompt": f"Public Legacy Prompt {uuid4().hex[:8]}",
        "public_review_template": review_template["name"],
        "public_review_template_label": review_template["template_name"],
        "public_rejected_template": rejected_template["name"],
        "public_rejected_template_label": rejected_template["template_name"],
        "public_archived_template": archived_template["name"],
        "public_archived_template_label": archived_template["template_name"],
        "public_tool_prompt": f"Public Tool Prompt {uuid4().hex[:8]}",
        "public_upload_template": public_upload_template["name"],
        "public_upload_template_label": public_upload_template["template_name"],
        "public_selected_asset": public_tool_asset["name"],
        "public_upload_url": f"https://example.invalid/e2e-public-created-{uuid4().hex[:8]}.png",
        "public_asset_workflow_run": public_asset_run["workflow_run"],
        "public_history_asset": public_asset_run["asset"],
        "public_unshared_history_asset": public_asset_run["unshared_asset"],
        "public_video_history_asset": public_asset_run["video_asset"],
        "public_audio_history_asset": public_asset_run["audio_asset"],
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
        "model_catalog_provider": catalog_model["provider"],
        "model_catalog_model": catalog_model["name"],
        "model_catalog_label": catalog_model["model_name"],
        "asset_workflow_run": asset_run["workflow_run"],
        "history_asset": asset_run["asset"],
        "video_history_asset": asset_run["video_asset"],
        "audio_history_asset": asset_run["audio_asset"],
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


def _ensure_public_tool_user() -> str:
    if frappe.db.exists("User", PUBLIC_TOOL_USER):
        user = frappe.get_doc("User", PUBLIC_TOOL_USER)
        user.enabled = 1
        user.user_type = "System User"
        user.save(ignore_permissions=True)
    else:
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": PUBLIC_TOOL_USER,
                "first_name": "Slow AI",
                "last_name": "Public E2E",
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
                "roles": [{"role": "Desk User"}],
            }
        ).insert(ignore_permissions=True)
    existing_roles = {row.role for row in user.get("roles", [])}
    if "Desk User" not in existing_roles:
        user.append("roles", {"role": "Desk User"})
        user.save(ignore_permissions=True)
    if "System Manager" in existing_roles:
        user.set("roles", [{"role": row.role} for row in user.get("roles", []) if row.role != "System Manager"])
        user.save(ignore_permissions=True)
    update_password(PUBLIC_TOOL_USER, PUBLIC_TOOL_PASSWORD)
    return PUBLIC_TOOL_USER


def _ensure_public_tool_member_user(email: str, password: str) -> str:
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
                "last_name": "Project Member E2E",
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
                "roles": [{"role": "Desk User"}],
            }
        ).insert(ignore_permissions=True)
    existing_roles = {row.role for row in user.get("roles", [])}
    if "Desk User" not in existing_roles:
        user.append("roles", {"role": "Desk User"})
        user.save(ignore_permissions=True)
    if "System Manager" in existing_roles:
        user.set("roles", [{"role": row.role} for row in user.get("roles", []) if row.role != "System Manager"])
        user.save(ignore_permissions=True)
    update_password(email, password)
    return email


def _create_project(owner: str | None = None):
    project = frappe.get_doc(
        {
            "doctype": "AI Project",
            "project_name": _unique("Browser E2E Project"),
            "status": "Open",
        }
    ).insert(ignore_permissions=True)
    if owner:
        frappe.db.set_value("AI Project", project.name, "owner", owner)
        project.reload()
    return project


def _create_tool_template(prefix: str = "Browser E2E Text Tool", status: str = "PUBLISHED") -> dict:
    template = frappe.call(
        "slow_ai.api.templates.save_template",
        template_name=_unique(prefix),
        status="DRAFT",
        category="Browser E2E",
        description="Browser E2E text prompt Tool Mode template",
        nodes=json.dumps(
            [
                {
                    "id": "prompt_1",
                    "type": "text_prompt",
                    "label": "Prompt",
                    "position": {"x": 96, "y": 128},
                    "config": {"text": "Template prompt", "text_style": "natural", "steps": 4},
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
        input_schema_json=json.dumps(
            [
                {
                    "id": "prompt",
                    "label": "Prompt",
                    "input_type": "LONG_TEXT",
                    "target_node_id": "prompt_1",
                    "target_config_field": "text",
                    "required": True,
                    "help": "Describe the output.",
                    "example": "A clean studio render",
                },
                {
                    "id": "style",
                    "label": "Style",
                    "input_type": "SELECT",
                    "target_node_id": "prompt_1",
                    "target_config_field": "text_style",
                    "default": "natural",
                    "options": [{"value": "natural", "label": "Natural"}, {"value": "studio", "label": "Studio"}],
                },
                {
                    "id": "steps",
                    "label": "Steps",
                    "input_type": "NUMBER",
                    "target_node_id": "prompt_1",
                    "target_config_field": "steps",
                    "default": 4,
                    "min": 1,
                    "max": 10,
                },
            ]
        ),
    )
    return _transition_template_fixture(template["name"], status)


def _create_legacy_tool_template(prefix: str = "Browser E2E Legacy Text Tool", status: str = "PUBLISHED") -> dict:
    template = frappe.call(
        "slow_ai.api.templates.save_template",
        template_name=_unique(prefix),
        status="DRAFT",
        category="Browser E2E",
        description="Browser E2E legacy no-schema text prompt Tool Mode template",
        nodes=json.dumps(
            [
                {
                    "id": "prompt_1",
                    "type": "text_prompt",
                    "label": "Prompt",
                    "position": {"x": 96, "y": 128},
                    "config": {"text": "Legacy template prompt"},
                },
                {
                    "id": "tool_output_1",
                    "type": "tool_output",
                    "label": "Tool Output",
                    "position": {"x": 376, "y": 128},
                    "config": {
                        "output_name": "answer",
                        "description": "Legacy text output",
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
        input_schema_json=json.dumps([]),
    )
    return _transition_template_fixture(template["name"], status)


def _create_upload_template(asset_name: str, prefix: str = "Browser E2E Upload Tool") -> dict:
    template = frappe.call(
        "slow_ai.api.templates.save_template",
        template_name=_unique(prefix),
        status="DRAFT",
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
        input_schema_json=json.dumps(
            [
                {
                    "id": "image",
                    "label": "Image",
                    "input_type": "IMAGE_ASSET",
                    "target_node_id": "asset_1",
                    "target_config_field": "asset",
                    "required": True,
                    "help": "Select or upload an image asset.",
                }
            ]
        ),
    )
    return _transition_template_fixture(template["name"], "PUBLISHED")


def _transition_template_fixture(template: str, status: str) -> dict:
    if status == "DRAFT":
        return frappe.call("slow_ai.api.templates.get_template", template=template)
    submitted = frappe.call("slow_ai.api.templates.submit_template_for_review", template=template)
    if status == "IN_REVIEW":
        return submitted
    if status == "REJECTED":
        return frappe.call(
            "slow_ai.api.templates.reject_template",
            template=template,
            rejection_reason="Browser E2E rejected fixture.",
        )
    approved = frappe.call(
        "slow_ai.api.templates.approve_template",
        template=template,
        review_notes="Browser E2E approved fixture.",
    )
    if status == "PUBLISHED":
        return approved
    if status == "ARCHIVED":
        return frappe.call("slow_ai.api.templates.archive_template", template=template, reason="Browser E2E archived fixture.")
    frappe.throw(f"Unsupported E2E template fixture status: {status}")


def _create_catalog_model() -> dict:
    provider = f"browser-e2e-model-provider-{uuid4().hex[:8]}"
    doc = frappe.get_doc(
        {
            "doctype": "AI Model",
            "model_id": f"{provider}/disabled-unpriced",
            "model_slug": f"{provider}-disabled-unpriced",
            "model_name": f"Browser E2E Disabled Unpriced Model {uuid4().hex[:8]}",
            "provider": provider,
            "status": "DISABLED",
            "node_type": "provider_text_to_image",
            "category": "provider",
            "modality": "TEXT_TO_IMAGE",
            "pricing_json": json.dumps({"unit": "run", "currency": "USD"}),
            "capabilities_json": json.dumps({"text_to_image": True}),
            "input_metadata_json": json.dumps({"prompt": "text", "size": "string"}),
            "output_metadata_json": json.dumps({"image": "AI Asset"}),
        }
    ).insert(ignore_permissions=True)
    return {"name": doc.name, "provider": provider, "model_name": doc.model_name}


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
    unshared_asset = frappe.get_doc(
        {
            "doctype": "AI Asset",
            "project": project,
            "asset_type": "IMAGE",
            "url": f"https://example.invalid/e2e-history-unshared-{uuid4().hex[:8]}.png",
            "mime_type": "image/png",
            "width": 320,
            "height": 240,
            "source_workflow_run": run["workflow_run"],
            "source_node_run": node_run,
            "metadata_json": json.dumps({"origin": "browser-e2e-history-unshared"}),
        }
    ).insert(ignore_permissions=True)
    video_asset = frappe.get_doc(
        {
            "doctype": "AI Asset",
            "project": project,
            "asset_type": "VIDEO",
            "url": f"https://example.invalid/e2e-history-video-{uuid4().hex[:8]}.mp4",
            "mime_type": "video/mp4",
            "width": 640,
            "height": 360,
            "duration_seconds": 2.5,
            "source_workflow_run": run["workflow_run"],
            "source_node_run": node_run,
            "metadata_json": json.dumps({"origin": "browser-e2e-history-video"}),
        }
    ).insert(ignore_permissions=True)
    audio_asset = frappe.get_doc(
        {
            "doctype": "AI Asset",
            "project": project,
            "asset_type": "AUDIO",
            "url": f"https://example.invalid/e2e-history-audio-{uuid4().hex[:8]}.mp3",
            "mime_type": "audio/mpeg",
            "duration_seconds": 1.5,
            "source_workflow_run": run["workflow_run"],
            "source_node_run": node_run,
            "metadata_json": json.dumps({"origin": "browser-e2e-history-audio"}),
        }
    ).insert(ignore_permissions=True)
    return {
        "workflow_run": run["workflow_run"],
        "asset": asset.name,
        "unshared_asset": unshared_asset.name,
        "video_asset": video_asset.name,
        "audio_asset": audio_asset.name,
    }


def _unique(prefix: str) -> str:
    return f"{prefix} {uuid4().hex[:8]}"

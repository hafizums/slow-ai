import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase


def unique(prefix: str) -> str:
    return f"{prefix} {uuid4().hex[:8]}"


def insert_doc(data: dict):
    return frappe.get_doc(data).insert(ignore_permissions=True)


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
                "last_name": "Schema User",
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
                "roles": [{"role": "Desk User"}],
            }
        ).insert(ignore_permissions=True)
    if "Desk User" not in {row.role for row in user.get("roles", [])}:
        user.append("roles", {"role": "Desk User"})
        user.save(ignore_permissions=True)
    return email


def create_project(owner: str):
    project = insert_doc(
        {
            "doctype": "AI Project",
            "project_name": unique("Template Schema Project"),
            "status": "Open",
        }
    )
    frappe.db.set_value("AI Project", project.name, "owner", owner)
    project.reload()
    return project


def add_member(project: str, user: str, role: str):
    return insert_doc(
        {
            "doctype": "AI Project Member",
            "project": project,
            "user": user,
            "role": role,
            "status": "ACTIVE",
        }
    )


def text_nodes():
    return [
        {
            "id": "prompt_1",
            "type": "text_prompt",
            "label": "Prompt",
            "position": {"x": 96, "y": 128},
            "config": {"text": "Template prompt", "style": "natural", "steps": 4, "enabled": False},
        },
        {
            "id": "tool_output_1",
            "type": "tool_output",
            "label": "Tool Output",
            "position": {"x": 376, "y": 128},
            "config": {"output_name": "answer", "description": "Primary output", "schema": {"type": "string"}},
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


def upload_nodes(asset_name: str):
    return [
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
            "config": {"output_name": "image", "description": "Selected image", "schema": {"type": "string"}},
        },
    ]


def upload_edges():
    return [
        {
            "id": "edge_1",
            "source": "asset_1",
            "source_port": "image",
            "target": "tool_output_1",
            "target_port": "image",
        }
    ]


def provider_nodes():
    return [
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
            "label": "Provider Image",
            "position": {"x": 376, "y": 128},
            "config": {"provider": "schema-provider", "model": "schema/model", "provider_account": "account"},
        },
        {
            "id": "output_1",
            "type": "export_output",
            "label": "Output",
            "position": {"x": 656, "y": 128},
            "config": {},
        },
    ]


def provider_edges():
    return [
        {"id": "edge_1", "source": "prompt_1", "source_port": "text", "target": "provider_1", "target_port": "prompt"},
        {"id": "edge_2", "source": "provider_1", "source_port": "image", "target": "output_1", "target_port": "image"},
    ]


def text_input_schema():
    return [
        {
            "id": "prompt",
            "label": "Prompt",
            "input_type": "LONG_TEXT",
            "target_node_id": "prompt_1",
            "target_config_field": "text",
            "required": True,
            "help": "Describe the output.",
            "example": "A clean product render",
        },
        {
            "id": "style",
            "label": "Style",
            "input_type": "SELECT",
            "target_node_id": "prompt_1",
            "target_config_field": "style",
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
        {
            "id": "enabled",
            "label": "Enabled",
            "input_type": "BOOLEAN",
            "target_node_id": "prompt_1",
            "target_config_field": "enabled",
            "default": False,
        },
    ]


def save_template(name: str, nodes, edges, input_schema=None, status: str = "PUBLISHED"):
    previous_user = frappe.session.user
    frappe.set_user("Administrator")
    try:
        return frappe.call(
            "slow_ai.api.templates.save_template",
            template_name=name,
            status=status,
            category="Template Schema Test",
            description="Template schema fixture",
            nodes=json.dumps(nodes),
            edges=json.dumps(edges),
            layout=json.dumps({"nodes": [{"id": nodes[0]["id"], "x": 96, "y": 128}]}),
            input_schema_json=json.dumps(input_schema or []),
        )
    finally:
        frappe.set_user(previous_user)


def create_asset(project: str, asset_type: str = "IMAGE"):
    return frappe.call(
        "slow_ai.api.assets.upload",
        project=project,
        asset_type=asset_type,
        url=f"https://example.invalid/{uuid4().hex}.png",
        mime_type="image/png",
        metadata=json.dumps({"origin": "template-input-schema-test"}),
    )


class TestTemplateInputSchema(FrappeTestCase):
    def setUp(self):
        self.previous_user = frappe.session.user
        self.owner = ensure_user(f"slow.ai.schema.owner.{uuid4().hex[:8]}@example.test")
        self.editor = ensure_user(f"slow.ai.schema.editor.{uuid4().hex[:8]}@example.test")
        self.viewer = ensure_user(f"slow.ai.schema.viewer.{uuid4().hex[:8]}@example.test")
        self.outsider = ensure_user(f"slow.ai.schema.outsider.{uuid4().hex[:8]}@example.test")
        frappe.set_user("Administrator")
        self.project = create_project(self.owner)

    def tearDown(self):
        frappe.set_user(self.previous_user)

    def test_template_save_normalizes_and_exposes_safe_schema(self):
        template = save_template(unique("Schema Text Template"), text_nodes(), text_edges(), text_input_schema())

        frappe.set_user(self.owner)
        loaded = frappe.call("slow_ai.api.public_tools.get_template", template=template["name"])

        self.assertEqual(loaded["input_schema"][0]["id"], "prompt")
        self.assertEqual(loaded["input_schema"][0]["input_type"], "LONG_TEXT")
        self.assertEqual(loaded["input_schema"][1]["options"][0]["value"], "natural")
        self.assertNotIn("api_key_secret", json.dumps(loaded, default=str))

    def test_invalid_schema_rejects_missing_target_and_unsafe_target_field(self):
        with self.assertRaises(frappe.ValidationError):
            save_template(
                unique("Missing Target Schema"),
                text_nodes(),
                text_edges(),
                [
                    {
                        "id": "bad",
                        "input_type": "TEXT",
                        "target_node_id": "missing",
                        "target_config_field": "text",
                    }
                ],
            )

        with self.assertRaises(frappe.ValidationError):
            save_template(
                unique("Unsafe Target Schema"),
                provider_nodes(),
                provider_edges(),
                [
                    {
                        "id": "model",
                        "input_type": "TEXT",
                        "target_node_id": "provider_1",
                        "target_config_field": "model",
                    }
                ],
            )

    def test_prepare_validates_values_and_persists_only_allowed_config_fields(self):
        template = save_template(unique("Prepare Schema Template"), text_nodes(), text_edges(), text_input_schema())
        frappe.set_user(self.owner)
        workflow = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=self.project.name,
            title="Prepared Schema Workflow",
            values={
                "prompt": "Prompt entered through schema",
                "style": "studio",
                "steps": "8",
                "enabled": "true",
            },
        )

        config = next(node for node in workflow["nodes"] if node["id"] == "prompt_1")["config"]
        self.assertEqual(config["text"], "Prompt entered through schema")
        self.assertEqual(config["style"], "studio")
        self.assertEqual(config["steps"], 8)
        self.assertTrue(config["enabled"])
        self.assertNotIn("provider", config)

    def test_prepare_rejects_required_select_number_and_extra_values(self):
        template = save_template(unique("Validation Schema Template"), text_nodes(), text_edges(), text_input_schema())
        frappe.set_user(self.owner)

        with self.assertRaises(frappe.ValidationError):
            frappe.call(
                "slow_ai.api.public_tools.prepare_workflow_from_template",
                template=template["name"],
                project=self.project.name,
                values={"style": "natural", "steps": 4},
            )
        with self.assertRaises(frappe.ValidationError):
            frappe.call(
                "slow_ai.api.public_tools.prepare_workflow_from_template",
                template=template["name"],
                project=self.project.name,
                values={"prompt": "x", "style": "forbidden", "steps": 4},
            )
        with self.assertRaises(frappe.ValidationError):
            frappe.call(
                "slow_ai.api.public_tools.prepare_workflow_from_template",
                template=template["name"],
                project=self.project.name,
                values={"prompt": "x", "style": "natural", "steps": 11},
            )
        with self.assertRaises(frappe.ValidationError):
            frappe.call(
                "slow_ai.api.public_tools.prepare_workflow_from_template",
                template=template["name"],
                project=self.project.name,
                values={"prompt": "x", "style": "natural", "steps": 4, "provider_account": "secret"},
            )

    def test_prepare_validates_asset_type_and_project_access(self):
        frappe.set_user(self.owner)
        image_asset = create_asset(self.project.name, "IMAGE")
        audio_asset = create_asset(self.project.name, "AUDIO")
        template = save_template(
            unique("Asset Schema Template"),
            upload_nodes(image_asset["name"]),
            upload_edges(),
            [
                {
                    "id": "image",
                    "label": "Image",
                    "input_type": "IMAGE_ASSET",
                    "target_node_id": "asset_1",
                    "target_config_field": "asset",
                    "required": True,
                }
            ],
        )

        workflow = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=self.project.name,
            values={"image": image_asset["name"]},
        )
        config = next(node for node in workflow["nodes"] if node["id"] == "asset_1")["config"]
        self.assertEqual(config["asset"], image_asset["name"])
        self.assertEqual(config["asset_type"], "IMAGE")

        with self.assertRaises(frappe.ValidationError):
            frappe.call(
                "slow_ai.api.public_tools.prepare_workflow_from_template",
                template=template["name"],
                project=self.project.name,
                values={"image": audio_asset["name"]},
            )

        other_project = create_project(self.outsider)
        frappe.set_user(self.outsider)
        inaccessible_asset = create_asset(other_project.name, "IMAGE")

        frappe.set_user(self.owner)
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.public_tools.prepare_workflow_from_template",
                template=template["name"],
                project=self.project.name,
                values={"image": inaccessible_asset["name"]},
            )

    def test_prepare_creates_no_execution_side_effect_records(self):
        template = save_template(unique("No Side Effects Schema Template"), text_nodes(), text_edges(), text_input_schema())
        counts = {
            doctype: frappe.db.count(doctype)
            for doctype in (
                "AI Provider Job",
                "AI Workflow Version",
                "AI Workflow Run",
                "AI Node Run",
                "AI Asset",
                "AI Credit Ledger",
            )
        }

        frappe.set_user(self.owner)
        workflow = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=self.project.name,
            values={"prompt": "No side effects", "style": "natural", "steps": 4},
        )

        self.assertTrue(frappe.db.exists("AI Workflow", workflow["name"]))
        for doctype, count in counts.items():
            self.assertEqual(frappe.db.count(doctype), count, doctype)

    def test_start_run_still_uses_normal_run_api_after_prepare(self):
        template = save_template(unique("Prepare Then Run Schema Template"), text_nodes(), text_edges(), text_input_schema())
        frappe.set_user(self.owner)
        workflow = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=self.project.name,
            values={"prompt": "Start through run API", "style": "natural", "steps": 4},
        )
        run = frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])

        self.assertTrue(frappe.db.exists("AI Workflow Version", run["workflow_version"]))
        self.assertTrue(frappe.db.exists("AI Workflow Run", run["workflow_run"]))

    def test_editor_can_prepare_and_viewer_is_rejected(self):
        add_member(self.project.name, self.editor, "EDITOR")
        add_member(self.project.name, self.viewer, "VIEWER")
        template = save_template(unique("Membership Schema Template"), text_nodes(), text_edges(), text_input_schema())

        frappe.set_user(self.editor)
        workflow = frappe.call(
            "slow_ai.api.public_tools.prepare_workflow_from_template",
            template=template["name"],
            project=self.project.name,
            values={"prompt": "Editor prompt", "style": "natural", "steps": 4},
        )

        frappe.set_user(self.viewer)
        with self.assertRaises(frappe.PermissionError):
            frappe.call(
                "slow_ai.api.public_tools.prepare_workflow_from_template",
                template=template["name"],
                project=self.project.name,
                values={"prompt": "Viewer prompt", "style": "natural", "steps": 4},
            )
        with self.assertRaises(frappe.PermissionError):
            frappe.call("slow_ai.api.runs.start_run", workflow=workflow["name"])

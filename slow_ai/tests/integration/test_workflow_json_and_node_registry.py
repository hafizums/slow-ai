import json

import frappe
from frappe.tests.utils import FrappeTestCase

from slow_ai.application.workflow_validation import validate_workflow
from slow_ai.domain.exceptions import GraphValidationError
from slow_ai.domain.workflow_json import parse_workflow_json, validate_workflow_json
from slow_ai.node_registry.nodes.text_prompt import TextPromptNode
from slow_ai.node_registry.nodes.upload_asset import UploadAssetNode
from slow_ai.node_registry.registry import create_default_registry


INITIAL_NODE_TYPES = {
    "text_prompt",
    "upload_asset",
    "provider_text_to_image",
    "provider_image_to_image",
    "provider_image_to_video",
    "provider_start_end_to_video",
    "provider_text_to_speech",
    "export_output",
}


def text_to_export_workflow():
    return {
        "nodes": [
            {
                "id": "prompt_1",
                "type": "text_prompt",
                "config": {"text": "A cinematic product shot"},
            },
            {"id": "output_1", "type": "export_output", "config": {}},
        ],
        "edges": [
            {
                "id": "edge_1",
                "source": "prompt_1",
                "source_port": "text",
                "target": "output_1",
                "target_port": "text",
            }
        ],
    }


class TestWorkflowJsonAndNodeRegistry(FrappeTestCase):
    def test_default_registry_exposes_initial_nodes(self):
        registry = create_default_registry()

        self.assertEqual({node.type for node in registry.all()}, INITIAL_NODE_TYPES)

    def test_object_info_api_returns_initial_node_schemas(self):
        object_info = frappe.get_attr("slow_ai.api.nodes.get_object_info")()
        nodes = object_info["nodes"]

        self.assertEqual(set(nodes), INITIAL_NODE_TYPES)
        self.assertEqual(nodes["text_prompt"]["output_schema"]["text"]["type"], "TEXT")
        self.assertEqual(nodes["upload_asset"]["output_schema"]["image"]["type"], "IMAGE_ASSET")
        self.assertEqual(nodes["provider_text_to_image"]["input_schema"]["prompt"]["type"], "TEXT")
        self.assertEqual(
            nodes["provider_image_to_video"]["output_schema"]["video"]["type"],
            "VIDEO_ASSET",
        )
        self.assertEqual(
            nodes["provider_text_to_speech"]["output_schema"]["audio"]["type"],
            "AUDIO_ASSET",
        )
        self.assertTrue(nodes["export_output"]["is_output_node"])

    def test_workflow_json_validation_accepts_text_to_export(self):
        graph = validate_workflow(text_to_export_workflow())

        self.assertEqual([node.id for node in graph.nodes], ["prompt_1", "output_1"])
        self.assertEqual(graph.edges[0].source_port, "text")

    def test_workflow_json_validation_accepts_json_string(self):
        graph = validate_workflow_json(json.dumps(text_to_export_workflow()))

        self.assertEqual(graph.nodes[0].type, "text_prompt")

    def test_upload_asset_image_can_connect_to_export_output(self):
        graph = validate_workflow(
            {
                "nodes": [
                    {
                        "id": "upload_1",
                        "type": "upload_asset",
                        "config": {"asset": "AI-ASSET-00001", "asset_type": "IMAGE"},
                    },
                    {"id": "output_1", "type": "export_output", "config": {}},
                ],
                "edges": [
                    {
                        "id": "edge_1",
                        "source": "upload_1",
                        "source_port": "image",
                        "target": "output_1",
                        "target_port": "image",
                    }
                ],
            }
        )

        self.assertEqual(graph.nodes[0].type, "upload_asset")

    def test_workflow_json_validation_rejects_missing_required_node_field(self):
        with self.assertRaises(GraphValidationError):
            parse_workflow_json({"nodes": [{"id": "prompt_1", "type": "text_prompt"}], "edges": []})

    def test_workflow_json_validation_rejects_port_type_mismatch(self):
        workflow = text_to_export_workflow()
        workflow["edges"][0]["target_port"] = "image"

        with self.assertRaises(GraphValidationError):
            validate_workflow(workflow)

    def test_workflow_json_validation_rejects_disconnected_output_node(self):
        with self.assertRaises(GraphValidationError):
            validate_workflow(
                {
                    "nodes": [{"id": "output_1", "type": "export_output", "config": {}}],
                    "edges": [],
                }
            )

    def test_text_prompt_execute_returns_configured_text(self):
        result = TextPromptNode().execute(
            context=None,
            inputs={},
            config={"text": "A cinematic product shot"},
        )

        self.assertEqual(result.outputs, {"text": "A cinematic product shot"})

    def test_upload_asset_rejects_invalid_asset_type(self):
        with self.assertRaises(GraphValidationError):
            UploadAssetNode().validate_config({"asset": "AI-ASSET-00001", "asset_type": "MODEL"})

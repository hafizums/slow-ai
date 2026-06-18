"""Uploaded asset reference node."""

from __future__ import annotations

from typing import Any, Mapping

from slow_ai.domain.ports import PortType
from slow_ai.node_registry.contracts import ExecutionContext, NodeDefinition, NodeExecutionResult
from slow_ai.node_registry.nodes.base import ConfigSchemaMixin


ASSET_TYPE_TO_OUTPUT = {
    "IMAGE": "image",
    "VIDEO": "video",
    "AUDIO": "audio",
    "MASK": "mask",
}


class UploadAssetNode(ConfigSchemaMixin, NodeDefinition):
    type = "upload_asset"
    label = "Upload Asset"
    category = "input"
    version = "1.0.0"
    is_output_node = False

    def input_schema(self) -> Mapping[str, Any]:
        return {}

    def config_schema(self) -> Mapping[str, Any]:
        return {
            "asset": {
                "type": "AI_ASSET",
                "value_type": "string",
                "required": True,
                "label": "AI Asset",
            },
            "asset_type": {
                "type": "TEXT",
                "value_type": "string",
                "required": True,
                "label": "Asset Type",
                "options": tuple(ASSET_TYPE_TO_OUTPUT.keys()),
            },
        }

    def output_schema(self) -> Mapping[str, Any]:
        return {
            "image": {"type": PortType.IMAGE_ASSET.value, "label": "Image"},
            "video": {"type": PortType.VIDEO_ASSET.value, "label": "Video"},
            "audio": {"type": PortType.AUDIO_ASSET.value, "label": "Audio"},
            "mask": {"type": PortType.MASK_ASSET.value, "label": "Mask"},
        }

    def execute(
        self,
        context: ExecutionContext,
        inputs: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> NodeExecutionResult:
        self.validate_config(config)
        output_name = ASSET_TYPE_TO_OUTPUT[str(config["asset_type"])]
        return NodeExecutionResult(outputs={output_name: config["asset"]}, asset_names=(config["asset"],))

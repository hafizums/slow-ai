"""Tool-mode output marker node."""

from __future__ import annotations

from typing import Any, Mapping

from slow_ai.domain.exceptions import GraphValidationError
from slow_ai.domain.ports import PortType
from slow_ai.node_registry.contracts import ExecutionContext, NodeDefinition, NodeExecutionResult
from slow_ai.node_registry.nodes.base import ConfigSchemaMixin


class ToolOutputNode(ConfigSchemaMixin, NodeDefinition):
    type = "tool_output"
    label = "Tool Output"
    category = "tool"
    version = "1.0.0"
    is_output_node = True

    def input_schema(self) -> Mapping[str, Any]:
        return {
            "text": {"type": PortType.TEXT.value, "label": "Text"},
            "image": {"type": PortType.IMAGE_ASSET.value, "label": "Image"},
            "video": {"type": PortType.VIDEO_ASSET.value, "label": "Video"},
            "audio": {"type": PortType.AUDIO_ASSET.value, "label": "Audio"},
            "mask": {"type": PortType.MASK_ASSET.value, "label": "Mask"},
            "json": {"type": PortType.JSON.value, "label": "JSON"},
        }

    def config_schema(self) -> Mapping[str, Any]:
        return {
            "output_name": {
                "type": PortType.TEXT.value,
                "value_type": "string",
                "required": True,
                "label": "Output Name",
            },
            "description": {
                "type": PortType.TEXT.value,
                "value_type": "string",
                "required": False,
                "label": "Description",
            },
            "schema": {
                "type": PortType.JSON.value,
                "value_type": "object",
                "required": False,
                "label": "Output Schema",
            },
        }

    def output_schema(self) -> Mapping[str, Any]:
        return {}

    def validate_inputs(self, inputs: Mapping[str, Any]) -> None:
        if not inputs:
            raise GraphValidationError("tool_output requires at least one connected input.")

    def execute(
        self,
        context: ExecutionContext,
        inputs: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> NodeExecutionResult:
        self.validate_config(config)
        self.validate_inputs(inputs)
        return NodeExecutionResult(
            outputs={
                "output_name": config["output_name"],
                "description": config.get("description") or "",
                "schema": config.get("schema") or {},
                "values": dict(inputs),
            }
        )

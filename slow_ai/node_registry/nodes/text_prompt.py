"""Text prompt node."""

from __future__ import annotations

from typing import Any, Mapping

from slow_ai.domain.ports import PortType
from slow_ai.node_registry.contracts import ExecutionContext, NodeDefinition, NodeExecutionResult
from slow_ai.node_registry.nodes.base import ConfigSchemaMixin


class TextPromptNode(ConfigSchemaMixin, NodeDefinition):
    type = "text_prompt"
    label = "Text Prompt"
    category = "input"
    version = "1.0.0"
    is_output_node = False

    def input_schema(self) -> Mapping[str, Any]:
        return {}

    def config_schema(self) -> Mapping[str, Any]:
        return {
            "text": {
                "type": PortType.TEXT.value,
                "value_type": "string",
                "required": True,
                "label": "Text",
            }
        }

    def output_schema(self) -> Mapping[str, Any]:
        return {
            "text": {
                "type": PortType.TEXT.value,
                "label": "Text",
            }
        }

    def execute(
        self,
        context: ExecutionContext,
        inputs: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> NodeExecutionResult:
        self.validate_config(config)
        return NodeExecutionResult(outputs={"text": config["text"]})

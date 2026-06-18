"""Node registry implementation."""

from __future__ import annotations

from collections.abc import Iterable

from slow_ai.domain.exceptions import RegistryError
from slow_ai.node_registry.contracts import NodeDefinition
from slow_ai.node_registry.schema import serialize_node_definition


FORBIDDEN_NODE_TYPE_FRAGMENTS = frozenset(
    {
        "checkpoint",
        "clip",
        "vae",
        "ksampler",
        "cuda",
        "gpu",
        "lora",
        "local_model",
        "tensor",
    }
)


class NodeRegistry:
    def __init__(self, nodes: Iterable[NodeDefinition] = ()) -> None:
        self._nodes: dict[str, NodeDefinition] = {}
        for node in nodes:
            self.register(node)

    def register(self, node: NodeDefinition) -> None:
        node_type = node.type.strip()
        if not node_type:
            raise RegistryError("Node type is required.")
        if self._is_forbidden_node_type(node_type):
            raise RegistryError(f"Local model node type is forbidden: {node_type}")
        if node_type in self._nodes:
            raise RegistryError(f"Node type is already registered: {node_type}")
        self._nodes[node_type] = node

    def get(self, node_type: str) -> NodeDefinition:
        try:
            return self._nodes[node_type]
        except KeyError as exc:
            raise RegistryError(f"Unknown node type: {node_type}") from exc

    def has(self, node_type: str) -> bool:
        return node_type in self._nodes

    def all(self) -> tuple[NodeDefinition, ...]:
        return tuple(self._nodes.values())

    def object_info(self) -> dict[str, dict]:
        return {
            node.type: serialize_node_definition(node)
            for node in sorted(self._nodes.values(), key=lambda item: item.type)
        }

    @staticmethod
    def _is_forbidden_node_type(node_type: str) -> bool:
        normalized = node_type.lower().replace("-", "_")
        return any(fragment in normalized for fragment in FORBIDDEN_NODE_TYPE_FRAGMENTS)


def create_default_registry() -> NodeRegistry:
    from slow_ai.node_registry.nodes.export_output import ExportOutputNode
    from slow_ai.node_registry.nodes.provider import (
        ProviderImageToImageNode,
        ProviderImageToVideoNode,
        ProviderStartEndToVideoNode,
        ProviderTextToImageNode,
        ProviderTextToSpeechNode,
    )
    from slow_ai.node_registry.nodes.text_prompt import TextPromptNode
    from slow_ai.node_registry.nodes.upload_asset import UploadAssetNode

    return NodeRegistry(
        [
            TextPromptNode(),
            UploadAssetNode(),
            ProviderTextToImageNode(),
            ProviderImageToImageNode(),
            ProviderImageToVideoNode(),
            ProviderStartEndToVideoNode(),
            ProviderTextToSpeechNode(),
            ExportOutputNode(),
        ]
    )

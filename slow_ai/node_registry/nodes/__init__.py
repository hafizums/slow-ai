"""Built-in node definitions."""

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

__all__ = [
    "ExportOutputNode",
    "ProviderImageToImageNode",
    "ProviderImageToVideoNode",
    "ProviderStartEndToVideoNode",
    "ProviderTextToImageNode",
    "ProviderTextToSpeechNode",
    "TextPromptNode",
    "UploadAssetNode",
]

"""Node catalog application service."""

from __future__ import annotations

from typing import Any

from slow_ai.node_registry.registry import NodeRegistry, create_default_registry


def get_object_info(node_registry: NodeRegistry | None = None) -> dict[str, Any]:
    registry = node_registry or create_default_registry()
    return {"nodes": registry.object_info()}

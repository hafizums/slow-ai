"""Workflow JSON parsing and validation entrypoints."""

from __future__ import annotations

import json
from typing import Any, Mapping

from slow_ai.domain.exceptions import GraphValidationError
from slow_ai.domain.graph_validator import GraphValidator
from slow_ai.domain.workflow_graph import WorkflowGraph
from slow_ai.node_registry.registry import NodeRegistry, create_default_registry


def parse_workflow_json(workflow_json: Mapping[str, Any] | str) -> WorkflowGraph:
    data = _coerce_mapping(workflow_json)
    nodes = _coerce_list(data, "nodes")
    edges = _coerce_list(data, "edges")

    for index, node in enumerate(nodes):
        _validate_node_object(node, index)
    for index, edge in enumerate(edges):
        _validate_edge_object(edge, index)

    return WorkflowGraph.from_dict({"nodes": nodes, "edges": edges})


def validate_workflow_json(
    workflow_json: Mapping[str, Any] | str,
    node_registry: NodeRegistry | None = None,
) -> WorkflowGraph:
    graph = parse_workflow_json(workflow_json)
    GraphValidator(node_registry or create_default_registry()).validate(graph)
    return graph


def _coerce_mapping(value: Mapping[str, Any] | str) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise GraphValidationError(f"Workflow JSON is invalid: {exc.msg}") from exc

    if not isinstance(value, Mapping):
        raise GraphValidationError("Workflow JSON must be an object.")
    return value


def _coerce_list(data: Mapping[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise GraphValidationError(f"Workflow JSON field must be a list: {key}")
    return value


def _validate_node_object(node: Any, index: int) -> None:
    if not isinstance(node, Mapping):
        raise GraphValidationError(f"Node at index {index} must be an object.")

    for fieldname in ("id", "type", "config"):
        if fieldname not in node:
            raise GraphValidationError(f"Node at index {index} is missing required field: {fieldname}")

    if not isinstance(node["id"], str) or not node["id"].strip():
        raise GraphValidationError(f"Node at index {index} must have a non-empty string id.")
    if not isinstance(node["type"], str) or not node["type"].strip():
        raise GraphValidationError(f"Node at index {index} must have a non-empty string type.")
    if not isinstance(node["config"], Mapping):
        raise GraphValidationError(f"Node at index {index} config must be an object.")
    if "position" in node and not isinstance(node["position"], Mapping):
        raise GraphValidationError(f"Node at index {index} position must be an object.")
    if "metadata" in node and not isinstance(node["metadata"], Mapping):
        raise GraphValidationError(f"Node at index {index} metadata must be an object.")


def _validate_edge_object(edge: Any, index: int) -> None:
    if not isinstance(edge, Mapping):
        raise GraphValidationError(f"Edge at index {index} must be an object.")

    for fieldname in ("id", "source", "source_port", "target", "target_port"):
        if fieldname not in edge:
            raise GraphValidationError(f"Edge at index {index} is missing required field: {fieldname}")
        if not isinstance(edge[fieldname], str) or not edge[fieldname].strip():
            raise GraphValidationError(
                f"Edge at index {index} must have a non-empty string {fieldname}."
            )

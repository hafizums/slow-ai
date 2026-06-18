"""Workflow graph value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class WorkflowNode:
    id: str
    type: str
    config: Mapping[str, Any] = field(default_factory=dict)
    label: str | None = None
    position: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkflowNode":
        return cls(
            id=str(data["id"]),
            type=str(data["type"]),
            config=data.get("config") or {},
            label=data.get("label"),
            position=data.get("position"),
            metadata=data.get("metadata") or {},
        )


@dataclass(frozen=True)
class WorkflowEdge:
    id: str
    source: str
    source_port: str
    target: str
    target_port: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkflowEdge":
        return cls(
            id=str(data["id"]),
            source=str(data["source"]),
            source_port=str(data["source_port"]),
            target=str(data["target"]),
            target_port=str(data["target_port"]),
        )


@dataclass(frozen=True)
class WorkflowGraph:
    nodes: tuple[WorkflowNode, ...]
    edges: tuple[WorkflowEdge, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkflowGraph":
        return cls(
            nodes=tuple(WorkflowNode.from_dict(node) for node in data.get("nodes", ())),
            edges=tuple(WorkflowEdge.from_dict(edge) for edge in data.get("edges", ())),
        )

    def node_by_id(self) -> dict[str, WorkflowNode]:
        return {node.id: node for node in self.nodes}

    def incoming_edges(self, node_id: str) -> tuple[WorkflowEdge, ...]:
        return tuple(edge for edge in self.edges if edge.target == node_id)

    def outgoing_edges(self, node_id: str) -> tuple[WorkflowEdge, ...]:
        return tuple(edge for edge in self.edges if edge.source == node_id)

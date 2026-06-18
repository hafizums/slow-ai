"""DAG helpers for workflow execution planning."""

from __future__ import annotations

from collections import defaultdict, deque

from slow_ai.domain.exceptions import GraphValidationError
from slow_ai.domain.workflow_graph import WorkflowGraph


def topological_sort(graph: WorkflowGraph) -> tuple[str, ...]:
    node_ids = {node.id for node in graph.nodes}
    incoming_count = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)

    for edge in graph.edges:
        if edge.source not in node_ids or edge.target not in node_ids:
            raise GraphValidationError("Edges must reference existing nodes before sorting.")
        outgoing[edge.source].append(edge.target)
        incoming_count[edge.target] += 1

    ready = deque(sorted(node_id for node_id, count in incoming_count.items() if count == 0))
    ordered: list[str] = []

    while ready:
        node_id = ready.popleft()
        ordered.append(node_id)
        for target_id in sorted(outgoing[node_id]):
            incoming_count[target_id] -= 1
            if incoming_count[target_id] == 0:
                ready.append(target_id)

    if len(ordered) != len(node_ids):
        raise GraphValidationError("Workflow graph must not contain cycles.")

    return tuple(ordered)

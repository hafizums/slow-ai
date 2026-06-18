"""Workflow graph validation rules."""

from __future__ import annotations

from collections import defaultdict

from slow_ai.domain.exceptions import GraphValidationError, RegistryError
from slow_ai.domain.ports import normalize_port_schema
from slow_ai.domain.workflow_graph import WorkflowGraph
from slow_ai.node_registry.registry import NodeRegistry


class GraphValidator:
    def __init__(self, node_registry: NodeRegistry) -> None:
        self.node_registry = node_registry

    def validate(self, graph: WorkflowGraph) -> None:
        self._validate_unique_node_ids(graph)
        self._validate_unique_edge_ids(graph)
        self._validate_nodes_exist_in_registry(graph)
        self._validate_edges_reference_existing_nodes(graph)
        self._validate_ports(graph)
        self._validate_required_inputs(graph)
        self._validate_output_node_exists(graph)
        self._validate_output_nodes_are_connected(graph)
        self._validate_acyclic(graph)

    def _validate_unique_node_ids(self, graph: WorkflowGraph) -> None:
        node_ids = [node.id for node in graph.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise GraphValidationError("All node ids must be unique.")

    def _validate_unique_edge_ids(self, graph: WorkflowGraph) -> None:
        edge_ids = [edge.id for edge in graph.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise GraphValidationError("All edge ids must be unique.")

    def _validate_nodes_exist_in_registry(self, graph: WorkflowGraph) -> None:
        for node in graph.nodes:
            try:
                definition = self.node_registry.get(node.type)
            except RegistryError as exc:
                raise GraphValidationError(str(exc)) from exc
            definition.validate_config(node.config)

    def _validate_edges_reference_existing_nodes(self, graph: WorkflowGraph) -> None:
        node_ids = {node.id for node in graph.nodes}
        for edge in graph.edges:
            if edge.source not in node_ids:
                raise GraphValidationError(f"Edge source does not exist: {edge.source}")
            if edge.target not in node_ids:
                raise GraphValidationError(f"Edge target does not exist: {edge.target}")

    def _validate_ports(self, graph: WorkflowGraph) -> None:
        nodes = graph.node_by_id()
        for edge in graph.edges:
            source_definition = self.node_registry.get(nodes[edge.source].type)
            target_definition = self.node_registry.get(nodes[edge.target].type)
            source_ports = normalize_port_schema(source_definition.output_schema())
            target_ports = normalize_port_schema(target_definition.input_schema())

            if edge.source_port not in source_ports:
                raise GraphValidationError(f"Source port does not exist: {edge.source_port}")
            if edge.target_port not in target_ports:
                raise GraphValidationError(f"Target port does not exist: {edge.target_port}")
            if source_ports[edge.source_port].port_type != target_ports[edge.target_port].port_type:
                raise GraphValidationError(
                    f"Port type mismatch: {edge.source}.{edge.source_port} "
                    f"to {edge.target}.{edge.target_port}"
                )

    def _validate_required_inputs(self, graph: WorkflowGraph) -> None:
        connected_inputs = {(edge.target, edge.target_port) for edge in graph.edges}
        for node in graph.nodes:
            definition = self.node_registry.get(node.type)
            input_ports = normalize_port_schema(definition.input_schema())
            for port_name, port_spec in input_ports.items():
                if not port_spec.required:
                    continue
                if (node.id, port_name) in connected_inputs:
                    continue
                if port_name in node.config:
                    continue
                raise GraphValidationError(f"Required input is missing: {node.id}.{port_name}")

    def _validate_output_node_exists(self, graph: WorkflowGraph) -> None:
        if not graph.nodes:
            raise GraphValidationError("Workflow graph must contain at least one node.")
        for node in graph.nodes:
            if self.node_registry.get(node.type).is_output_node:
                return
        raise GraphValidationError("At least one output node is required.")

    def _validate_output_nodes_are_connected(self, graph: WorkflowGraph) -> None:
        for node in graph.nodes:
            definition = self.node_registry.get(node.type)
            if definition.is_output_node and definition.input_schema() and not graph.incoming_edges(node.id):
                raise GraphValidationError(f"Output node requires at least one input: {node.id}")

    def _validate_acyclic(self, graph: WorkflowGraph) -> None:
        outgoing: dict[str, list[str]] = defaultdict(list)
        for edge in graph.edges:
            outgoing[edge.source].append(edge.target)

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise GraphValidationError("Workflow graph must not contain cycles.")
            if node_id in visited:
                return

            visiting.add(node_id)
            for target_id in outgoing[node_id]:
                visit(target_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node in graph.nodes:
            visit(node.id)

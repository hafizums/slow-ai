from typing import Any, Mapping

from frappe.tests.utils import FrappeTestCase

from slow_ai.domain.exceptions import (
    GraphValidationError,
    ProviderInvariantError,
    RegistryError,
    StateTransitionError,
)
from slow_ai.domain.graph_validator import GraphValidator
from slow_ai.domain.ports import PortType
from slow_ai.domain.status import NodeRunStatus, WorkflowRunStatus
from slow_ai.domain.workflow_graph import WorkflowGraph
from slow_ai.doctype.contracts import PERMANENT_DOCTYPES
from slow_ai.engine.dag import topological_sort
from slow_ai.engine.state_machine import transition_node_run, transition_workflow_run
from slow_ai.node_registry.contracts import (
    ExecutionContext,
    NodeDefinition,
    NodeExecutionResult,
)
from slow_ai.node_registry.registry import (
    FORBIDDEN_NODE_TYPE_FRAGMENTS,
    NodeRegistry,
    create_default_registry,
)
from slow_ai.providers.contracts import ProviderSubmission


INITIAL_NODE_TYPES = {
    "text_prompt",
    "upload_asset",
    "provider_text_to_image",
    "provider_image_to_image",
    "provider_image_to_video",
    "provider_start_end_to_video",
    "provider_text_to_speech",
    "export_output",
}


class TextPromptNode(NodeDefinition):
    type = "text_prompt"
    label = "Text Prompt"
    category = "input"
    version = "1.0.0"

    def input_schema(self) -> Mapping[str, Any]:
        return {"text": {"type": PortType.TEXT.value, "required": False}}

    def config_schema(self) -> Mapping[str, Any]:
        return {"text": {"type": PortType.TEXT.value, "required": True}}

    def output_schema(self) -> Mapping[str, Any]:
        return {"text": {"type": PortType.TEXT.value}}

    def validate_inputs(self, inputs: Mapping[str, Any]) -> None:
        return None

    def validate_config(self, config: Mapping[str, Any]) -> None:
        if not config.get("text"):
            raise GraphValidationError("text_prompt.text is required.")

    def execute(
        self,
        context: ExecutionContext,
        inputs: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> NodeExecutionResult:
        return NodeExecutionResult(outputs={"text": config["text"]})


class ExportOutputNode(NodeDefinition):
    type = "export_output"
    label = "Export Output"
    category = "output"
    version = "1.0.0"
    is_output_node = True

    def input_schema(self) -> Mapping[str, Any]:
        return {"text": {"type": PortType.TEXT.value, "required": True}}

    def config_schema(self) -> Mapping[str, Any]:
        return {}

    def output_schema(self) -> Mapping[str, Any]:
        return {"text": {"type": PortType.TEXT.value}}

    def validate_inputs(self, inputs: Mapping[str, Any]) -> None:
        return None

    def validate_config(self, config: Mapping[str, Any]) -> None:
        return None

    def execute(
        self,
        context: ExecutionContext,
        inputs: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> NodeExecutionResult:
        return NodeExecutionResult(outputs=dict(inputs))


def make_registry() -> NodeRegistry:
    return NodeRegistry([TextPromptNode(), ExportOutputNode()])


def valid_graph() -> WorkflowGraph:
    return WorkflowGraph.from_dict(
        {
            "nodes": [
                {
                    "id": "prompt_1",
                    "type": "text_prompt",
                    "config": {"text": "A product shot"},
                },
                {"id": "output_1", "type": "export_output", "config": {}},
            ],
            "edges": [
                {
                    "id": "edge_1",
                    "source": "prompt_1",
                    "source_port": "text",
                    "target": "output_1",
                    "target_port": "text",
                }
            ],
        }
    )


class TestPlatformKernel(FrappeTestCase):
    def test_platform_kernel_layers_are_importable(self):
        expected_doctypes = {
            "AI Project",
            "AI Workflow",
            "AI Workflow Version",
            "AI Workflow Run",
            "AI Node Run",
            "AI Asset",
            "AI Provider Job",
            "AI Model",
            "AI Provider Account",
            "AI Credit Ledger",
            "AI Workflow Template",
        }

        self.assertEqual(set(PERMANENT_DOCTYPES), expected_doctypes)
        self.assertEqual(topological_sort(valid_graph()), ("prompt_1", "output_1"))

    def test_valid_graph_passes_contract_validation(self):
        GraphValidator(make_registry()).validate(valid_graph())

    def test_graph_validation_rejects_cycle(self):
        graph = WorkflowGraph.from_dict(
            {
                "nodes": [
                    {"id": "prompt_1", "type": "text_prompt", "config": {"text": "A"}},
                    {"id": "output_1", "type": "export_output", "config": {}},
                ],
                "edges": [
                    {
                        "id": "edge_1",
                        "source": "prompt_1",
                        "source_port": "text",
                        "target": "output_1",
                        "target_port": "text",
                    },
                    {
                        "id": "edge_2",
                        "source": "output_1",
                        "source_port": "text",
                        "target": "prompt_1",
                        "target_port": "text",
                    },
                ],
            }
        )

        with self.assertRaises(GraphValidationError):
            GraphValidator(make_registry()).validate(graph)

    def test_unknown_node_type_is_rejected(self):
        graph = WorkflowGraph.from_dict(
            {
                "nodes": [{"id": "node_1", "type": "unknown", "config": {}}],
                "edges": [],
            }
        )

        with self.assertRaises(GraphValidationError):
            GraphValidator(make_registry()).validate(graph)

    def test_state_machine_rejects_invalid_transition(self):
        self.assertEqual(
            transition_workflow_run(WorkflowRunStatus.DRAFT, WorkflowRunStatus.QUEUED),
            WorkflowRunStatus.QUEUED,
        )
        self.assertEqual(
            transition_node_run(NodeRunStatus.PENDING, NodeRunStatus.READY),
            NodeRunStatus.READY,
        )

        with self.assertRaises(StateTransitionError):
            transition_workflow_run(WorkflowRunStatus.SUCCEEDED, WorkflowRunStatus.RUNNING)

    def test_provider_submission_requires_existing_provider_job(self):
        with self.assertRaises(ProviderInvariantError):
            ProviderSubmission(provider_job_name="", model="wavespeed/model", input_data={})

        submission = ProviderSubmission(
            provider_job_name="AI-PROVIDER-JOB-0001",
            model="wavespeed/model",
            input_data={"prompt": "A product shot"},
        )
        self.assertEqual(submission.provider_job_name, "AI-PROVIDER-JOB-0001")

    def test_no_local_model_nodes_are_registered(self):
        registry = create_default_registry()
        registered_types = {node.type for node in registry.all()}
        self.assertEqual(registered_types, INITIAL_NODE_TYPES)
        self.assertFalse(
            any(
                fragment in node_type
                for node_type in registered_types
                for fragment in FORBIDDEN_NODE_TYPE_FRAGMENTS
            )
        )

        with self.assertRaises(RegistryError):
            registry.register(type("CheckpointNode", (TextPromptNode,), {"type": "checkpoint_loader"})())

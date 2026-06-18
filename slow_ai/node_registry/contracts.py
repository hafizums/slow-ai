"""Node definition contract used by the workflow engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ExecutionContext:
    workflow_run_name: str
    node_run_name: str
    project_name: str | None = None
    user: str | None = None


@dataclass(frozen=True)
class NodeExecutionResult:
    outputs: Mapping[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    provider_job_name: str | None = None
    asset_names: tuple[str, ...] = ()
    waiting_provider: bool = False


class NodeDefinition(ABC):
    type: str
    label: str
    category: str
    version: str
    is_output_node: bool = False

    @abstractmethod
    def input_schema(self) -> Mapping[str, Any]:
        """Return input port schema keyed by port name."""

    @abstractmethod
    def config_schema(self) -> Mapping[str, Any]:
        """Return config schema keyed by config field name."""

    @abstractmethod
    def output_schema(self) -> Mapping[str, Any]:
        """Return output port schema keyed by port name."""

    @abstractmethod
    def validate_inputs(self, inputs: Mapping[str, Any]) -> None:
        """Validate already-resolved runtime inputs."""

    @abstractmethod
    def validate_config(self, config: Mapping[str, Any]) -> None:
        """Validate node configuration before a run is created."""

    @abstractmethod
    def execute(
        self,
        context: ExecutionContext,
        inputs: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> NodeExecutionResult:
        """Execute node logic through persisted workflow state."""

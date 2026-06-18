"""Shared helpers for built-in node definitions."""

from __future__ import annotations

from typing import Any, Mapping

from slow_ai.domain.exceptions import GraphValidationError
from slow_ai.node_registry.schema import validate_config_schema


class ConfigSchemaMixin:
    type: str

    def validate_config(self, config: Mapping[str, Any]) -> None:
        validate_config_schema(self.type, config, self.config_schema())

    def validate_inputs(self, inputs: Mapping[str, Any]) -> None:
        required_inputs = [
            name for name, spec in self.input_schema().items() if bool(spec.get("required", False))
        ]
        for input_name in required_inputs:
            if input_name not in inputs or inputs[input_name] in (None, ""):
                raise GraphValidationError(f"{self.type}.{input_name} input is required.")

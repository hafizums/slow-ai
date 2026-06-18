"""Port type contracts shared by graph validation and node definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class PortType(str, Enum):
    TEXT = "TEXT"
    IMAGE_ASSET = "IMAGE_ASSET"
    VIDEO_ASSET = "VIDEO_ASSET"
    AUDIO_ASSET = "AUDIO_ASSET"
    MASK_ASSET = "MASK_ASSET"
    JSON = "JSON"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"


@dataclass(frozen=True)
class PortSpec:
    name: str
    port_type: PortType
    required: bool = False


def normalize_port_spec(name: str, raw_spec: PortSpec | Mapping[str, Any] | str) -> PortSpec:
    if isinstance(raw_spec, PortSpec):
        return raw_spec

    if isinstance(raw_spec, str):
        return PortSpec(name=name, port_type=PortType(raw_spec), required=False)

    return PortSpec(
        name=name,
        port_type=PortType(str(raw_spec["type"])),
        required=bool(raw_spec.get("required", False)),
    )


def normalize_port_schema(raw_schema: Mapping[str, Any]) -> dict[str, PortSpec]:
    return {name: normalize_port_spec(name, spec) for name, spec in raw_schema.items()}

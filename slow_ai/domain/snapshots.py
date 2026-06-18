"""Snapshot helpers for immutable workflow versions."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def canonical_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()

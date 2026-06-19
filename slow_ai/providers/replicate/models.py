"""Replicate provider constants and local catalog seed helpers."""

from __future__ import annotations

import json
from typing import Any

import frappe


REPLICATE_PROVIDER_NAME = "replicate"
REPLICATE_BASE_URL = "https://api.replicate.com/v1"

REPLICATE_MODEL_CATALOG = (
    {
        "model_id": "black-forest-labs/flux-schnell",
        "model_slug": "replicate-flux-schnell",
        "model_name": "Replicate Flux Schnell",
        "status": "ENABLED",
        "modality": "TEXT_TO_IMAGE",
        "node_type": "provider_text_to_image",
        "category": "provider",
        "pricing_json": {
            "unit": "run",
            "test_cost_usd": "0.003",
            "currency": "USD",
            "source": "replicate_first_second_provider_test_guard",
            "test_parameters": {
                "num_outputs": 1,
                "aspect_ratio": "1:1",
                "output_format": "webp",
                "output_quality": 80,
                "num_inference_steps": 4,
            },
        },
        "capabilities_json": {"text_to_image": True},
        "input_metadata_json": {
            "prompt": "text",
            "num_outputs": "number",
            "aspect_ratio": "string",
            "output_format": "string",
            "output_quality": "number",
            "num_inference_steps": "number",
        },
        "output_metadata_json": {"image": "AI Asset"},
    },
)


def upsert_replicate_model_catalog() -> list[str]:
    """Create or update known Replicate AI Model rows without provider calls."""

    names = []
    for entry in REPLICATE_MODEL_CATALOG:
        values = _doctype_values(entry)
        if frappe.db.exists("AI Model", entry["model_id"]):
            doc = frappe.get_doc("AI Model", entry["model_id"])
            doc.update(values)
            doc.save(ignore_permissions=True)
        else:
            doc = frappe.get_doc({"doctype": "AI Model", **values}).insert(ignore_permissions=True)
        names.append(doc.name)
    return names


def _doctype_values(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_id": entry["model_id"],
        "model_slug": entry["model_slug"],
        "model_name": entry["model_name"],
        "provider": REPLICATE_PROVIDER_NAME,
        "status": entry["status"],
        "modality": entry["modality"],
        "node_type": entry["node_type"],
        "category": entry["category"],
        "pricing_json": json.dumps(entry["pricing_json"]),
        "capabilities_json": json.dumps(entry["capabilities_json"]),
        "input_metadata_json": json.dumps(entry["input_metadata_json"]),
        "output_metadata_json": json.dumps(entry["output_metadata_json"]),
    }

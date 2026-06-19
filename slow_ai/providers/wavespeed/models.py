"""WaveSpeed provider constants and local catalog seed helpers."""

from __future__ import annotations

import json
from typing import Any

import frappe

WAVESPEED_PROVIDER_NAME = "wavespeed"
WAVESPEED_BASE_URL = "https://api.wavespeed.ai/api/v3"

WAVESPEED_MODEL_CATALOG = (
    {
        "model_id": "wavespeed-ai/flux-dev",
        "model_slug": "wavespeed-flux-dev",
        "model_name": "WaveSpeed Flux Dev",
        "status": "ENABLED",
        "modality": "TEXT_TO_IMAGE",
        "node_type": "provider_text_to_image",
        "category": "provider",
        "pricing_json": {"unit": "run", "amount_usd": "0.012", "currency": "USD"},
        "capabilities_json": {"text_to_image": True},
        "input_metadata_json": {"prompt": "text", "size": "string"},
        "output_metadata_json": {"image": "AI Asset"},
    },
    {
        "model_id": "wavespeed-ai/z-image/turbo",
        "model_slug": "wavespeed-z-image-turbo",
        "model_name": "WaveSpeed Z-Image Turbo",
        "status": "DISABLED",
        "modality": "TEXT_TO_IMAGE",
        "node_type": "provider_text_to_image",
        "category": "provider",
        "pricing_json": {"unit": "run", "currency": "USD"},
        "capabilities_json": {"text_to_image": True},
        "input_metadata_json": {"prompt": "text", "size": "string"},
        "output_metadata_json": {"image": "AI Asset"},
    },
)


def upsert_wavespeed_model_catalog() -> list[str]:
    """Create or update known WaveSpeed AI Model rows without provider calls."""

    names = []
    for entry in WAVESPEED_MODEL_CATALOG:
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
        "provider": WAVESPEED_PROVIDER_NAME,
        "status": entry["status"],
        "modality": entry["modality"],
        "node_type": entry["node_type"],
        "category": entry["category"],
        "pricing_json": json.dumps(entry["pricing_json"]),
        "capabilities_json": json.dumps(entry["capabilities_json"]),
        "input_metadata_json": json.dumps(entry["input_metadata_json"]),
        "output_metadata_json": json.dumps(entry["output_metadata_json"]),
    }

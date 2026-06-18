"""AI Model metadata API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.models import get_model_metadata as get_model_metadata_service


@frappe.whitelist()
def get_model_metadata(model_ids) -> dict:
    return get_model_metadata_service(model_ids)

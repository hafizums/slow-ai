"""AI Model metadata API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.models import get_model as get_model_service
from slow_ai.application.models import get_model_metadata as get_model_metadata_service
from slow_ai.application.models import list_models as list_models_service


@frappe.whitelist()
def get_model_metadata(model_ids) -> dict:
    return get_model_metadata_service(model_ids)


@frappe.whitelist()
def list_models(provider=None, status="ENABLED", node_type=None) -> dict:
    return list_models_service(provider=provider, status=status, node_type=node_type)


@frappe.whitelist()
def get_model(model) -> dict:
    return get_model_service(model)

"""AI Model metadata API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.models import get_model as get_model_service
from slow_ai.application.models import get_model_metadata as get_model_metadata_service
from slow_ai.application.models import list_models as list_models_service
from slow_ai.application.models import update_model_metadata as update_model_metadata_service
from slow_ai.application.models import update_model_pricing as update_model_pricing_service
from slow_ai.application.models import update_model_status as update_model_status_service


@frappe.whitelist()
def get_model_metadata(model_ids) -> dict:
    return get_model_metadata_service(model_ids)


@frappe.whitelist()
def list_models(provider=None, status="ENABLED", node_type=None, category=None) -> dict:
    return list_models_service(provider=provider, status=status, node_type=node_type, category=category)


@frappe.whitelist()
def get_model(model) -> dict:
    return get_model_service(model)


@frappe.whitelist()
def update_model_status(model, status) -> dict:
    return update_model_status_service(model, status)


@frappe.whitelist()
def update_model_pricing(model, amount_usd=None, unit="run", currency="USD") -> dict:
    return update_model_pricing_service(model, amount_usd, unit, currency)


@frappe.whitelist()
def update_model_metadata(model, capabilities=None, input_metadata=None, output_metadata=None) -> dict:
    return update_model_metadata_service(model, capabilities, input_metadata, output_metadata)

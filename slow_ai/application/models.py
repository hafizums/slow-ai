"""AI Model metadata application services."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

import frappe


PRICE_KEYS = ("test_cost_usd", "amount_usd", "base_price", "price_usd")
MODEL_SAFE_FIELDS = [
    "name",
    "model_id",
    "model_slug",
    "model_name",
    "provider",
    "status",
    "modality",
    "node_type",
    "category",
    "pricing_json",
    "capabilities_json",
    "input_metadata_json",
    "output_metadata_json",
]


def list_models(
    provider: str | None = None,
    status: str | None = "ENABLED",
    node_type: str | None = None,
) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    provider = _clean_optional(provider)
    status = _clean_optional(status)
    node_type = _clean_optional(node_type)
    if provider:
        filters["provider"] = provider
    if status and status.upper() != "ALL":
        filters["status"] = status.upper()
    if node_type:
        filters["node_type"] = node_type

    rows = frappe.get_all(
        "AI Model",
        filters=filters,
        fields=MODEL_SAFE_FIELDS,
        order_by="provider asc, model_name asc, model_id asc",
    )
    return {"models": [_safe_model_payload(row) for row in rows]}


def get_model(model: str) -> dict[str, Any]:
    model_ref = str(model or "").strip()
    if not model_ref:
        frappe.throw("model is required.")
    row = _get_model_row(model_ref)
    if not row:
        frappe.throw(f"AI Model is not configured: {model_ref}.")
    return {"model": _safe_model_payload(row)}


def get_model_metadata(model_ids: Any) -> dict[str, Any]:
    requested_ids = _loads_model_ids(model_ids)
    if not requested_ids:
        return {"models": {}}

    rows = _get_model_rows(requested_ids)
    models = {}
    for row in rows:
        payload = _safe_model_payload(row)
        models[row.name] = payload
        models[row.model_id] = payload
        if row.model_slug:
            models[row.model_slug] = payload
    return {"models": models}


def _loads_model_ids(model_ids: Any) -> list[str]:
    if model_ids is None or model_ids == "":
        return []
    values = json.loads(model_ids) if isinstance(model_ids, str) else model_ids
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        frappe.throw("model_ids must be a list of model IDs.")
    seen = set()
    result = []
    for value in values:
        model_id = str(value).strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        result.append(model_id)
    return result


def pricing_summary_from_json(pricing_json: str | None) -> dict[str, Any]:
    if not pricing_json:
        return _unknown_pricing()
    try:
        pricing = json.loads(pricing_json)
    except json.JSONDecodeError:
        return _unknown_pricing()
    if not isinstance(pricing, dict):
        return _unknown_pricing()

    amount = _first_price(pricing)
    if amount is None:
        return _unknown_pricing(pricing.get("currency"), pricing.get("unit"))
    return {
        "pricing_known": True,
        "estimated_cost_usd": str(amount),
        "pricing_unit": pricing.get("unit") or "run",
        "currency": pricing.get("currency") or "USD",
    }


def _first_price(pricing: dict[str, Any]) -> Decimal | None:
    for key in PRICE_KEYS:
        value = pricing.get(key)
        if value in (None, ""):
            continue
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        if amount >= 0:
            return amount
    return None


def _unknown_pricing(currency: str | None = None, unit: str | None = None) -> dict[str, Any]:
    return {
        "pricing_known": False,
        "estimated_cost_usd": None,
        "pricing_unit": unit or "run",
        "currency": currency or "USD",
    }


def _get_model_row(model_ref: str):
    rows = _get_model_rows([model_ref])
    return rows[0] if rows else None


def _get_model_rows(model_refs: list[str]):
    rows_by_name: dict[str, Any] = {}
    for fieldname in ("name", "model_id", "model_slug"):
        rows = frappe.get_all(
            "AI Model",
            filters={fieldname: ["in", model_refs]},
            fields=MODEL_SAFE_FIELDS,
            order_by="creation asc",
        )
        for row in rows:
            rows_by_name[row.name] = row
    return list(rows_by_name.values())


def _safe_model_payload(row) -> dict[str, Any]:
    pricing = pricing_summary_from_json(row.pricing_json)
    return {
        "name": row.name,
        "model_id": row.model_id,
        "model_slug": row.model_slug,
        "model_name": row.model_name,
        "display_name": row.model_name,
        "provider": row.provider,
        "status": row.status,
        "modality": row.modality,
        "node_type": row.node_type,
        "category": row.category,
        "pricing_known": pricing["pricing_known"],
        "estimated_cost_usd": pricing["estimated_cost_usd"],
        "pricing_unit": pricing["pricing_unit"],
        "currency": pricing["currency"],
        "capabilities": _safe_json_object(row.capabilities_json),
        "input_metadata": _safe_json_object(row.input_metadata_json),
        "output_metadata": _safe_json_object(row.output_metadata_json),
    }


def _safe_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_optional(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip() or None

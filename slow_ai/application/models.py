"""AI Model metadata application services."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

import frappe


PRICE_KEYS = ("test_cost_usd", "amount_usd", "base_price", "price_usd")


def get_model_metadata(model_ids: Any) -> dict[str, Any]:
    requested_ids = _loads_model_ids(model_ids)
    if not requested_ids:
        return {"models": {}}

    rows = frappe.get_all(
        "AI Model",
        filters={"name": ["in", requested_ids]},
        fields=["name", "model_id", "model_name", "provider", "status", "modality", "pricing_json"],
    )
    models = {}
    for row in rows:
        pricing = pricing_summary_from_json(row.pricing_json)
        payload = {
            "name": row.name,
            "model_id": row.model_id,
            "model_name": row.model_name,
            "provider": row.provider,
            "status": row.status,
            "modality": row.modality,
            "pricing_known": pricing["pricing_known"],
            "estimated_cost_usd": pricing["estimated_cost_usd"],
            "pricing_unit": pricing["pricing_unit"],
            "currency": pricing["currency"],
        }
        models[row.name] = payload
        models[row.model_id] = payload
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

"""AI Credit Ledger application services."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import frappe


LEDGER_SAFE_FIELDS = [
    "name",
    "project",
    "workflow_run",
    "node_run",
    "provider_job",
    "ledger_type",
    "amount_usd",
    "currency",
    "description",
    "reference_doctype",
    "reference_name",
    "creation",
    "owner",
]


def create_top_up(
    project: str,
    amount_usd: Any,
    description: str | None = None,
    reference_doctype: str | None = None,
    reference_name: str | None = None,
) -> dict[str, Any]:
    frappe.only_for("System Manager")
    project_name = _require_project(project)
    amount = _as_positive_decimal(amount_usd, "amount_usd")
    ledger = frappe.get_doc(
        {
            "doctype": "AI Credit Ledger",
            "project": project_name,
            "ledger_type": "CREDIT",
            "amount_usd": str(amount),
            "currency": "USD",
            "description": description or "Credit top-up",
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
        }
    ).insert(ignore_permissions=True)
    return {"ledger": _ledger_payload(ledger.as_dict()), "balance": get_balance(project_name)}


def get_balance(project: str, user: str | None = None) -> dict[str, Any]:
    project_name = _require_project(project)
    rows = _ledger_rows(project_name, user=user)
    credits = Decimal("0")
    debits = Decimal("0")
    adjustments = Decimal("0")
    for row in rows:
        amount = _as_decimal(row.amount_usd)
        if row.ledger_type == "CREDIT":
            credits += amount
        elif row.ledger_type == "DEBIT":
            debits += amount
        elif row.ledger_type == "ADJUSTMENT":
            adjustments += amount

    balance = credits + adjustments - debits
    return {
        "project": project_name,
        "user": user,
        "currency": "USD",
        "credits_usd": str(credits),
        "debits_usd": str(debits),
        "adjustments_usd": str(adjustments),
        "balance_usd": str(balance),
    }


def get_ledger(project: str, user: str | None = None, limit: int | str = 50) -> dict[str, Any]:
    project_name = _require_project(project)
    rows = frappe.get_all(
        "AI Credit Ledger",
        filters=_ledger_filters(project_name, user),
        fields=LEDGER_SAFE_FIELDS,
        order_by="creation desc",
        limit=_as_limit(limit),
    )
    return {
        "project": project_name,
        "user": user,
        "ledger": [_ledger_payload(row) for row in rows],
        "balance": get_balance(project_name, user=user),
    }


def get_project_balance_usd(project: str) -> Decimal:
    return Decimal(get_balance(project)["balance_usd"])


def assert_project_has_balance(project: str, estimated_cost_usd: Decimal) -> None:
    from slow_ai.domain.exceptions import RunPreflightError

    balance = get_project_balance_usd(project)
    if estimated_cost_usd > balance:
        raise RunPreflightError(
            "Workflow estimated provider cost "
            f"{estimated_cost_usd} USD exceeds available project credit balance "
            f"{balance} USD."
        )


def _ledger_rows(project: str, user: str | None = None):
    return frappe.get_all(
        "AI Credit Ledger",
        filters=_ledger_filters(project, user),
        fields=["ledger_type", "amount_usd"],
        order_by="creation asc",
    )


def _ledger_filters(project: str, user: str | None = None) -> dict[str, Any]:
    filters: dict[str, Any] = {"project": project}
    if user:
        filters["owner"] = user
    return filters


def _ledger_payload(row) -> dict[str, Any]:
    payload = {field: row.get(field) for field in LEDGER_SAFE_FIELDS if field in row}
    if "amount_usd" in payload:
        payload["amount_usd"] = str(_as_decimal(payload["amount_usd"]))
    return payload


def _require_project(project: str) -> str:
    project_name = str(project or "").strip()
    if not project_name:
        frappe.throw("project is required.")
    if not frappe.db.exists("AI Project", project_name):
        frappe.throw(f"AI Project does not exist: {project_name}.")
    return project_name


def _as_positive_decimal(value: Any, label: str) -> Decimal:
    amount = _as_decimal(value)
    if amount <= 0:
        frappe.throw(f"{label} must be greater than zero.")
    return amount


def _as_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        frappe.throw("amount_usd must be a decimal value.")


def _as_limit(value: int | str) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 50
    return max(1, min(limit, 500))

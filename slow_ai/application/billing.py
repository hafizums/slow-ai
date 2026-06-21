"""AI Credit Ledger application services."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

import frappe

from slow_ai.application.project_access import assert_can_manage_billing, assert_can_view_billing


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
RESERVE = "RESERVE"
RELEASE = "RELEASE"
DEBIT = "DEBIT"
CREDIT = "CREDIT"
ADJUSTMENT = "ADJUSTMENT"


def create_top_up(
    project: str,
    amount_usd: Any,
    description: str | None = None,
    reference_doctype: str | None = None,
    reference_name: str | None = None,
) -> dict[str, Any]:
    project_name = _require_project(project)
    assert_can_manage_billing(project_name)
    amount = _as_positive_decimal(amount_usd, "amount_usd")
    ledger = frappe.get_doc(
        {
            "doctype": "AI Credit Ledger",
            "project": project_name,
            "ledger_type": CREDIT,
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
    assert_can_view_billing(project_name)
    rows = _ledger_rows(project_name, user=user)
    credits = Decimal("0")
    debits = Decimal("0")
    adjustments = Decimal("0")
    reserves = Decimal("0")
    releases = Decimal("0")
    for row in rows:
        amount = _as_decimal(row.amount_usd)
        if row.ledger_type == CREDIT:
            credits += amount
        elif row.ledger_type == DEBIT:
            debits += amount
        elif row.ledger_type == ADJUSTMENT:
            adjustments += amount
        elif row.ledger_type == RESERVE:
            reserves += amount
        elif row.ledger_type == RELEASE:
            releases += amount

    balance = credits + adjustments + releases - debits - reserves
    return {
        "project": project_name,
        "user": user,
        "currency": "USD",
        "credits_usd": str(credits),
        "debits_usd": str(debits),
        "adjustments_usd": str(adjustments),
        "reserved_usd": str(reserves),
        "released_usd": str(releases),
        "balance_usd": str(balance),
    }


def get_ledger(project: str, user: str | None = None, limit: int | str = 50) -> dict[str, Any]:
    project_name = _require_project(project)
    assert_can_view_billing(project_name)
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
    rows = _ledger_rows(_require_project(project))
    credits = Decimal("0")
    debits = Decimal("0")
    adjustments = Decimal("0")
    reserves = Decimal("0")
    releases = Decimal("0")
    for row in rows:
        amount = _as_decimal(row.amount_usd)
        if row.ledger_type == CREDIT:
            credits += amount
        elif row.ledger_type == DEBIT:
            debits += amount
        elif row.ledger_type == ADJUSTMENT:
            adjustments += amount
        elif row.ledger_type == RESERVE:
            reserves += amount
        elif row.ledger_type == RELEASE:
            releases += amount
    return credits + adjustments + releases - debits - reserves


def assert_project_has_balance(project: str, estimated_cost_usd: Decimal) -> None:
    from slow_ai.domain.exceptions import RunPreflightError

    balance = get_project_balance_usd(project)
    if estimated_cost_usd > balance:
        raise RunPreflightError(
            "Workflow estimated provider cost "
            f"{estimated_cost_usd} USD exceeds available project credit balance "
            f"{balance} USD."
        )


def create_run_reservations(
    *,
    project: str,
    workflow_run: str,
    provider_runs: tuple[Any, ...],
    node_runs_by_node_id: dict[str, str],
) -> tuple[str, ...]:
    project_name = _require_project(project)
    reservation_names: list[str] = []
    for provider_run in provider_runs:
        amount = _as_decimal(getattr(provider_run, "estimated_cost_usd", 0))
        if amount <= 0:
            continue
        node_run_name = node_runs_by_node_id.get(provider_run.node_id)
        if not node_run_name:
            continue
        existing = frappe.db.get_value(
            "AI Credit Ledger",
            {
                "workflow_run": workflow_run,
                "node_run": node_run_name,
                "ledger_type": RESERVE,
            },
            "name",
        )
        if existing:
            reservation_names.append(existing)
            continue
        assert_project_has_balance(project_name, amount)
        ledger = frappe.get_doc(
            {
                "doctype": "AI Credit Ledger",
                "project": project_name,
                "workflow_run": workflow_run,
                "node_run": node_run_name,
                "ledger_type": RESERVE,
                "amount_usd": amount,
                "currency": "USD",
                "description": "Reserved estimated provider cost",
                "reference_doctype": "AI Model",
                "reference_name": provider_run.model_name,
                "metadata_json": _json(
                    {
                        "provider": provider_run.provider,
                        "model": provider_run.model,
                        "model_name": provider_run.model_name,
                        "node_id": provider_run.node_id,
                        "node_type": provider_run.node_type,
                        "estimated_cost_usd": str(amount),
                    }
                ),
            }
        ).insert(ignore_permissions=True)
        reservation_names.append(ledger.name)
    return tuple(reservation_names)


def link_reservation_to_provider_job(node_run: str | None, provider_job: str) -> None:
    if not node_run or not provider_job:
        return
    for reservation in frappe.get_all(
        "AI Credit Ledger",
        filters={"node_run": node_run, "ledger_type": RESERVE},
        fields=["name", "metadata_json"],
    ):
        metadata = _loads_json(reservation.metadata_json, {})
        if metadata.get("provider_job"):
            continue
        metadata["provider_job"] = provider_job
        frappe.db.set_value("AI Credit Ledger", reservation.name, "metadata_json", _json(metadata))


def release_provider_reservation(
    *,
    workflow_run: str,
    node_run: str | None = None,
    provider_job: str | None = None,
    description: str = "Released provider cost reservation",
) -> tuple[str, ...]:
    filters: dict[str, Any] = {"workflow_run": workflow_run, "ledger_type": RESERVE}
    if node_run:
        filters["node_run"] = node_run
    elif provider_job:
        job_node_run = frappe.db.get_value("AI Provider Job", provider_job, "node_run")
        if job_node_run:
            filters["node_run"] = job_node_run
        else:
            filters["provider_job"] = provider_job
    reservations = frappe.get_all(
        "AI Credit Ledger",
        filters=filters,
        fields=["name", "project", "workflow_run", "node_run", "provider_job", "amount_usd", "metadata_json"],
        order_by="creation asc",
    )
    release_names: list[str] = []
    for reservation in reservations:
        existing = frappe.db.get_value(
            "AI Credit Ledger",
            {
                "ledger_type": RELEASE,
                "reference_doctype": "AI Credit Ledger",
                "reference_name": reservation.name,
            },
            "name",
        )
        if existing:
            release_names.append(existing)
            continue
        metadata = _loads_json(reservation.metadata_json, {})
        if provider_job and not metadata.get("provider_job"):
            metadata["provider_job"] = provider_job
        release = frappe.get_doc(
            {
                "doctype": "AI Credit Ledger",
                "project": reservation.project,
                "workflow_run": reservation.workflow_run,
                "node_run": reservation.node_run,
                "ledger_type": RELEASE,
                "amount_usd": _as_decimal(reservation.amount_usd),
                "currency": "USD",
                "description": description,
                "reference_doctype": "AI Credit Ledger",
                "reference_name": reservation.name,
                "metadata_json": _json(metadata),
            }
        ).insert(ignore_permissions=True)
        release_names.append(release.name)
    return tuple(release_names)


def release_run_reservations(workflow_run: str, description: str = "Released run cost reservation") -> tuple[str, ...]:
    if not workflow_run:
        return ()
    if not frappe.db.exists("AI Workflow Run", workflow_run):
        return ()
    return release_provider_reservation(workflow_run=workflow_run, description=description)


def get_reserved_amount_for_provider_job(provider_job: str) -> Decimal:
    doc = frappe.get_doc("AI Provider Job", provider_job)
    filters: dict[str, Any] = {"ledger_type": RESERVE}
    if doc.node_run:
        filters["node_run"] = doc.node_run
    else:
        filters["provider_job"] = provider_job
    rows = frappe.get_all("AI Credit Ledger", filters=filters, fields=["amount_usd"])
    total = Decimal("0")
    for row in rows:
        total += _as_decimal(row.amount_usd)
    return total


def assert_provider_debit_within_reserved_or_available(
    *,
    project: str,
    provider_job: str,
    amount_usd: Decimal,
) -> None:
    if frappe.db.exists("AI Credit Ledger", {"provider_job": provider_job, "ledger_type": DEBIT}):
        return
    reserved = get_reserved_amount_for_provider_job(provider_job)
    if reserved <= 0:
        return
    extra = amount_usd - reserved
    if extra <= 0:
        return
    balance = get_project_balance_usd(project)
    if extra > balance:
        from slow_ai.domain.exceptions import ProviderInvariantError

        raise ProviderInvariantError(
            "Provider actual cost exceeds reserved estimate and available project credit balance."
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


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _loads_json(value: Any, default: Any) -> Any:
    if not value:
        return default
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, dict):
        return dict(value)
    return default


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

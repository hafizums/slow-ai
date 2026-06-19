"""AI billing API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.billing import create_top_up as create_top_up_service
from slow_ai.application.billing import get_balance as get_balance_service
from slow_ai.application.billing import get_ledger as get_ledger_service


@frappe.whitelist()
def create_top_up(project, amount_usd, description=None, reference_doctype=None, reference_name=None) -> dict:
    return create_top_up_service(project, amount_usd, description, reference_doctype, reference_name)


@frappe.whitelist()
def get_balance(project, user=None) -> dict:
    return get_balance_service(project, user)


@frappe.whitelist()
def get_ledger(project, user=None, limit=50) -> dict:
    return get_ledger_service(project, user, limit)

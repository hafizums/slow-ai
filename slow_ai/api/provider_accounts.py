"""AI Provider Account API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.provider_accounts import create_account as create_account_service
from slow_ai.application.provider_accounts import disable_account as disable_account_service
from slow_ai.application.provider_accounts import get_account as get_account_service
from slow_ai.application.provider_accounts import list_accounts as list_accounts_service
from slow_ai.application.provider_accounts import set_default as set_default_service


@frappe.whitelist()
def list_accounts(provider=None, project=None, user=None, include_disabled=False) -> dict:
    return list_accounts_service(provider, project, user, include_disabled)


@frappe.whitelist()
def get_account(account) -> dict:
    return get_account_service(account)


@frappe.whitelist()
def create_account(provider, account_label, api_key, project=None, user=None, is_default=False, rate_limit=None) -> dict:
    return create_account_service(provider, account_label, api_key, project, user, is_default, rate_limit)


@frappe.whitelist()
def set_default(account) -> dict:
    return set_default_service(account)


@frappe.whitelist()
def disable_account(account) -> dict:
    return disable_account_service(account)

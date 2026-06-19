"""Frappe helpers for AI Provider Account resolution."""

from __future__ import annotations

from typing import Any

import frappe


PROVIDER_ACCOUNT_SAFE_FIELDS = [
    "name",
    "provider",
    "account_label",
    "status",
    "is_default",
    "project",
    "user",
    "owner",
    "creation",
    "modified",
]


def resolve_provider_account_name(
    provider: str,
    provider_account_name: Any | None = None,
    *,
    project_name: str | None = None,
    user: str | None = None,
    require_default: bool = False,
    error_cls: type[Exception] = ValueError,
) -> str | None:
    provider_name = str(provider or "").strip()
    if not provider_name:
        raise error_cls("Provider is required for provider account resolution.")

    current_user = _clean_optional(user) or frappe.session.user
    configured_account = _clean_optional(provider_account_name)
    if configured_account:
        return _resolve_configured_account(
            provider_name,
            configured_account,
            project_name=project_name,
            user=current_user,
            error_cls=error_cls,
        )

    account_name = _find_default_account(provider_name, project_name=project_name, user=current_user)
    if account_name:
        return account_name
    if require_default:
        raise error_cls(f"No active default provider account is configured for {provider_name}.")
    return None


def account_matches_scope(account, *, project_name: str | None = None, user: str | None = None) -> bool:
    account_project = _clean_optional(account.get("project") if isinstance(account, dict) else account.project)
    account_user = _clean_optional(account.get("user") if isinstance(account, dict) else account.user)
    requested_project = _clean_optional(project_name)
    requested_user = _clean_optional(user) or frappe.session.user
    if account_project and account_project != requested_project:
        return False
    if account_user and account_user != requested_user:
        return False
    return True


def safe_account_payload(row) -> dict[str, Any]:
    return {field: row.get(field) for field in PROVIDER_ACCOUNT_SAFE_FIELDS if field in row}


def _resolve_configured_account(
    provider: str,
    account_name: str,
    *,
    project_name: str | None,
    user: str | None,
    error_cls: type[Exception],
) -> str:
    if not frappe.db.exists("AI Provider Account", account_name):
        raise error_cls(f"Provider account is not configured: {account_name}.")
    account = frappe.get_doc("AI Provider Account", account_name)
    if account.provider != provider:
        raise error_cls(
            f"Provider account {account.name} belongs to provider {account.provider}, not {provider}."
        )
    if account.status != "ACTIVE":
        raise error_cls(f"Provider account {account.name} is not active.")
    if not account_matches_scope(account, project_name=project_name, user=user):
        raise error_cls(f"Provider account {account.name} is not allowed for this project or user.")
    return account.name


def _find_default_account(provider: str, *, project_name: str | None, user: str | None) -> str | None:
    rows = frappe.get_all(
        "AI Provider Account",
        filters={"provider": provider, "status": "ACTIVE", "is_default": 1},
        fields=["name", "project", "user"],
        order_by="creation asc",
    )
    for row in rows:
        if account_matches_scope(row, project_name=project_name, user=user):
            return row.name
    return None


def _clean_optional(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None

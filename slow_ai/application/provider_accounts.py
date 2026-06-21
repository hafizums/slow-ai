"""Safe AI Provider Account application services."""

from __future__ import annotations

import json
from typing import Any

import frappe

from slow_ai.application.project_access import can_manage_provider_accounts, assert_can_manage_provider_accounts, is_system_manager
from slow_ai.infrastructure.provider_accounts import PROVIDER_ACCOUNT_SAFE_FIELDS, safe_account_payload


def list_accounts(
    provider: str | None = None,
    project: str | None = None,
    user: str | None = None,
    include_disabled: bool | str | int = False,
) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    provider_name = _clean_optional(provider)
    project_name = _clean_optional(project)
    user_name = _clean_optional(user)
    if provider_name:
        filters["provider"] = provider_name
    if project_name:
        filters["project"] = project_name
        assert_can_manage_provider_accounts(project_name)
    elif not _is_system_manager():
        filters["user"] = frappe.session.user
    if user_name:
        filters["user"] = user_name
    if not _as_bool(include_disabled):
        filters["status"] = "ACTIVE"

    rows = frappe.get_all(
        "AI Provider Account",
        filters=filters,
        fields=PROVIDER_ACCOUNT_SAFE_FIELDS,
        order_by="provider asc, account_label asc, creation asc",
    )
    return {"accounts": [safe_account_payload(row) for row in rows if _can_view_account(row)]}


def get_account(account: str) -> dict[str, Any]:
    account_name = _require_account_name(account)
    doc = frappe.get_doc("AI Provider Account", account_name)
    _assert_can_manage_account(doc)
    return {"account": safe_account_payload(doc.as_dict())}


def create_account(
    provider: str,
    account_label: str,
    api_key: str,
    project: str | None = None,
    user: str | None = None,
    is_default: bool | str | int = False,
    rate_limit: Any | None = None,
) -> dict[str, Any]:
    _assert_not_guest()
    provider_name = _clean_required(provider, "provider")
    label = _clean_required(account_label, "account_label")
    secret = _clean_required(api_key, "api_key")
    project_name = _validate_project(project)
    user_name = _validate_user(user)
    if project_name:
        assert_can_manage_provider_accounts(project_name)
    elif not _is_system_manager():
        frappe.throw("Project is required to create a provider account.", frappe.PermissionError)
    if user_name and user_name != frappe.session.user and not _is_system_manager():
        frappe.throw("You cannot create a provider account for another user.")
    if not user_name and not _is_system_manager():
        user_name = frappe.session.user

    account = frappe.get_doc(
        {
            "doctype": "AI Provider Account",
            "provider": provider_name,
            "account_label": label,
            "project": project_name,
            "user": user_name,
            "api_key_secret": secret,
            "is_default": 1 if _as_bool(is_default) else 0,
            "status": "ACTIVE",
            "rate_limit_json": _json_or_none(rate_limit),
        }
    ).insert(ignore_permissions=True)
    if account.is_default:
        _unset_other_defaults(account)
    return {"account": safe_account_payload(account.as_dict())}


def set_default(account: str) -> dict[str, Any]:
    account_name = _require_account_name(account)
    doc = frappe.get_doc("AI Provider Account", account_name)
    _assert_can_manage_account(doc)
    if doc.status != "ACTIVE":
        frappe.throw("Only active provider accounts can be set as default.")
    frappe.db.set_value("AI Provider Account", doc.name, "is_default", 1)
    doc.reload()
    _unset_other_defaults(doc)
    return {"account": safe_account_payload(doc.as_dict())}


def disable_account(account: str) -> dict[str, Any]:
    account_name = _require_account_name(account)
    doc = frappe.get_doc("AI Provider Account", account_name)
    _assert_can_manage_account(doc)
    frappe.db.set_value("AI Provider Account", doc.name, {"status": "DISABLED", "is_default": 0})
    doc.reload()
    return {"account": safe_account_payload(doc.as_dict())}


def _unset_other_defaults(account) -> None:
    rows = frappe.get_all(
        "AI Provider Account",
        filters={"provider": account.provider, "is_default": 1},
        fields=["name", "project", "user"],
    )
    for row in rows:
        if row.name == account.name:
            continue
        if _scope_key(row) == _scope_key(account):
            frappe.db.set_value("AI Provider Account", row.name, "is_default", 0)


def _can_view_account(row) -> bool:
    if _is_system_manager():
        return True
    current_user = frappe.session.user
    if row.get("project"):
        return can_manage_provider_accounts(row.get("project"))
    return row.owner == current_user or row.get("user") == current_user


def _assert_can_manage_account(account) -> None:
    if _is_system_manager():
        return
    current_user = frappe.session.user
    if account.project:
        if can_manage_provider_accounts(account.project):
            return
        frappe.throw("You are not allowed to manage this provider account.", frappe.PermissionError)
    if account.owner == current_user or account.user == current_user:
        return
    frappe.throw("You are not allowed to manage this provider account.", frappe.PermissionError)


def _assert_not_guest() -> None:
    if frappe.session.user == "Guest":
        frappe.throw("Login is required to manage provider accounts.", frappe.PermissionError)


def _is_system_manager() -> bool:
    return is_system_manager()


def _require_account_name(account: str) -> str:
    account_name = _clean_required(account, "account")
    if not frappe.db.exists("AI Provider Account", account_name):
        frappe.throw(f"AI Provider Account does not exist: {account_name}.")
    return account_name


def _validate_project(project: str | None) -> str | None:
    project_name = _clean_optional(project)
    if project_name and not frappe.db.exists("AI Project", project_name):
        frappe.throw(f"AI Project does not exist: {project_name}.")
    return project_name


def _validate_user(user: str | None) -> str | None:
    user_name = _clean_optional(user)
    if user_name and not frappe.db.exists("User", user_name):
        frappe.throw(f"User does not exist: {user_name}.")
    return user_name


def _scope_key(account) -> tuple[str | None, str | None]:
    return (_clean_optional(account.project), _clean_optional(account.user))


def _clean_required(value: Any, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        frappe.throw(f"{label} is required.")
    return cleaned


def _clean_optional(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _json_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)

"""Project membership policy and management services."""

from __future__ import annotations

from typing import Any, Iterable

import frappe


PROJECT_ROLES = frozenset({"OWNER", "EDITOR", "VIEWER", "BILLING"})
PROJECT_STATUSES = frozenset({"ACTIVE", "DISABLED"})
VIEW_ROLES = frozenset({"OWNER", "EDITOR", "VIEWER", "BILLING"})
EDIT_ROLES = frozenset({"OWNER", "EDITOR"})
RUN_ROLES = frozenset({"OWNER", "EDITOR"})
MANAGE_ROLES = frozenset({"OWNER"})
BILLING_ROLES = frozenset({"OWNER", "BILLING"})
PROVIDER_ACCOUNT_ROLES = frozenset({"OWNER", "BILLING"})
SHARE_ROLES = frozenset({"OWNER", "EDITOR"})


def can_view_project(project: str, user: str | None = None) -> bool:
    return _has_project_role(project, VIEW_ROLES, user=user)


def can_edit_project(project: str, user: str | None = None) -> bool:
    return _has_project_role(project, EDIT_ROLES, user=user)


def can_run_project(project: str, user: str | None = None) -> bool:
    return _has_project_role(project, RUN_ROLES, user=user)


def can_manage_project_members(project: str, user: str | None = None) -> bool:
    return _has_project_role(project, MANAGE_ROLES, user=user)


def can_view_billing(project: str, user: str | None = None) -> bool:
    return _has_project_role(project, BILLING_ROLES, user=user)


def can_manage_billing(project: str, user: str | None = None) -> bool:
    return _has_project_role(project, BILLING_ROLES, user=user)


def can_manage_provider_accounts(project: str, user: str | None = None) -> bool:
    return _has_project_role(project, PROVIDER_ACCOUNT_ROLES, user=user)


def can_share_run(project: str, user: str | None = None) -> bool:
    return _has_project_role(project, SHARE_ROLES, user=user)


def assert_can_view_project(project: str, user: str | None = None) -> str:
    return _assert_project_role(project, VIEW_ROLES, "view this AI Project", user=user)


def assert_can_edit_project(project: str, user: str | None = None) -> str:
    return _assert_project_role(project, EDIT_ROLES, "edit this AI Project", user=user)


def assert_can_run_project(project: str, user: str | None = None) -> str:
    return _assert_project_role(project, RUN_ROLES, "start runs for this AI Project", user=user)


def assert_can_manage_project_members(project: str, user: str | None = None) -> str:
    return _assert_project_role(project, MANAGE_ROLES, "manage members for this AI Project", user=user)


def assert_can_view_billing(project: str, user: str | None = None) -> str:
    return _assert_project_role(project, BILLING_ROLES, "view billing for this AI Project", user=user)


def assert_can_manage_billing(project: str, user: str | None = None) -> str:
    return _assert_project_role(project, BILLING_ROLES, "manage billing for this AI Project", user=user)


def assert_can_manage_provider_accounts(project: str, user: str | None = None) -> str:
    return _assert_project_role(project, PROVIDER_ACCOUNT_ROLES, "manage provider accounts for this AI Project", user=user)


def assert_can_share_run(project: str, user: str | None = None) -> str:
    return _assert_project_role(project, SHARE_ROLES, "share runs for this AI Project", user=user)


def list_accessible_project_names(permission: str = "view", user: str | None = None) -> list[str]:
    current_user = _current_user(user)
    if _is_system_manager(current_user):
        return frappe.get_all("AI Project", pluck="name", order_by="modified desc")

    roles = _roles_for_permission(permission)
    names = set(frappe.get_all("AI Project", filters={"owner": current_user}, pluck="name"))
    member_rows = frappe.get_all(
        "AI Project Member",
        filters={"user": current_user, "status": "ACTIVE", "role": ["in", list(roles)]},
        fields=["project"],
    )
    names.update(row.project for row in member_rows)
    return sorted(names)


def list_my_projects() -> dict[str, Any]:
    projects = []
    for project_name in list_accessible_project_names("view"):
        project = frappe.get_doc("AI Project", project_name)
        projects.append(
            {
                "name": project.name,
                "project_name": project.project_name,
                "status": project.status,
                "role": get_project_role(project.name),
                "owner": project.owner,
                "modified": project.modified,
            }
        )
    return {"projects": projects}


def list_members(project: str) -> dict[str, Any]:
    project_name = assert_can_manage_project_members(project)
    rows = frappe.get_all(
        "AI Project Member",
        filters={"project": project_name},
        fields=["name", "project", "user", "role", "status", "owner", "creation", "modified"],
        order_by="creation asc",
    )
    return {"project": project_name, "members": [_member_payload(row) for row in rows]}


def add_member(project: str, user: str, role: str) -> dict[str, Any]:
    project_name = assert_can_manage_project_members(project)
    user_name = _require_user(user)
    normalized_role = _normalize_role(role)
    existing = frappe.get_all(
        "AI Project Member",
        filters={"project": project_name, "user": user_name},
        fields=["name"],
        order_by="modified desc",
        limit=1,
    )
    if existing:
        doc = frappe.get_doc("AI Project Member", existing[0].name)
        doc.role = normalized_role
        doc.status = "ACTIVE"
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc(
            {
                "doctype": "AI Project Member",
                "project": project_name,
                "user": user_name,
                "role": normalized_role,
                "status": "ACTIVE",
            }
        ).insert(ignore_permissions=True)
    return {"member": _member_payload(doc.as_dict())}


def update_member_role(member: str, role: str) -> dict[str, Any]:
    doc = _get_member_doc(member)
    assert_can_manage_project_members(doc.project)
    doc.role = _normalize_role(role)
    doc.save(ignore_permissions=True)
    return {"member": _member_payload(doc.as_dict())}


def disable_member(member: str) -> dict[str, Any]:
    doc = _get_member_doc(member)
    assert_can_manage_project_members(doc.project)
    doc.status = "DISABLED"
    doc.save(ignore_permissions=True)
    return {"member": _member_payload(doc.as_dict())}


def get_project_role(project: str, user: str | None = None) -> str | None:
    project_name = _require_project(project)
    current_user = _current_user(user)
    if _is_system_manager(current_user):
        return "SYSTEM_MANAGER"
    if frappe.db.get_value("AI Project", project_name, "owner") == current_user:
        return "OWNER"
    return frappe.db.get_value(
        "AI Project Member",
        {"project": project_name, "user": current_user, "status": "ACTIVE"},
        "role",
    )


def require_logged_in_user() -> None:
    if frappe.session.user == "Guest":
        frappe.throw("Login is required.", frappe.PermissionError)


def is_system_manager(user: str | None = None) -> bool:
    return _is_system_manager(_current_user(user))


def _assert_project_role(project: str, allowed_roles: Iterable[str], action: str, user: str | None = None) -> str:
    project_name = _require_project(project)
    if not _has_project_role(project_name, allowed_roles, user=user, project_checked=True):
        frappe.throw(f"You are not allowed to {action}.", frappe.PermissionError)
    return project_name


def _has_project_role(
    project: str,
    allowed_roles: Iterable[str],
    user: str | None = None,
    project_checked: bool = False,
) -> bool:
    project_name = project if project_checked else _require_project(project)
    current_user = _current_user(user)
    if current_user == "Guest":
        return False
    if _is_system_manager(current_user):
        return True
    if "OWNER" in allowed_roles and frappe.db.get_value("AI Project", project_name, "owner") == current_user:
        return True
    role = frappe.db.get_value(
        "AI Project Member",
        {"project": project_name, "user": current_user, "status": "ACTIVE"},
        "role",
    )
    return bool(role in set(allowed_roles))


def _roles_for_permission(permission: str) -> frozenset[str]:
    if permission == "edit":
        return EDIT_ROLES
    if permission == "run":
        return RUN_ROLES
    if permission == "billing":
        return BILLING_ROLES
    if permission == "provider_accounts":
        return PROVIDER_ACCOUNT_ROLES
    if permission == "share":
        return SHARE_ROLES
    return VIEW_ROLES


def _require_project(project: str) -> str:
    project_name = str(project or "").strip()
    if not project_name:
        frappe.throw("AI Project is required.", frappe.PermissionError)
    if not frappe.db.exists("AI Project", project_name):
        frappe.throw(f"AI Project does not exist: {project_name}.", frappe.PermissionError)
    return project_name


def _require_user(user: str) -> str:
    user_name = str(user or "").strip()
    if not user_name:
        frappe.throw("User is required.")
    if user_name == "Guest":
        frappe.throw("Guest cannot be added to an AI Project.")
    if not frappe.db.exists("User", user_name):
        frappe.throw(f"User does not exist: {user_name}.")
    return user_name


def _normalize_role(role: str) -> str:
    normalized = str(role or "").strip().upper()
    if normalized not in PROJECT_ROLES:
        frappe.throw(f"Unsupported AI Project member role: {role}.")
    return normalized


def _get_member_doc(member: str):
    member_name = str(member or "").strip()
    if not member_name or not frappe.db.exists("AI Project Member", member_name):
        frappe.throw("AI Project Member does not exist.")
    return frappe.get_doc("AI Project Member", member_name)


def _member_payload(row) -> dict[str, Any]:
    return {
        "name": row.get("name"),
        "project": row.get("project"),
        "user": row.get("user"),
        "role": row.get("role"),
        "status": row.get("status"),
        "owner": row.get("owner"),
        "created": row.get("creation"),
        "modified": row.get("modified"),
    }


def _current_user(user: str | None = None) -> str:
    return str(user or frappe.session.user or "Guest")


def _is_system_manager(user: str) -> bool:
    if user == "Administrator":
        return True
    return "System Manager" in frappe.get_roles(user)

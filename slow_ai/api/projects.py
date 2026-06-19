"""AI Project membership API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.project_access import add_member as add_member_service
from slow_ai.application.project_access import disable_member as disable_member_service
from slow_ai.application.project_access import list_members as list_members_service
from slow_ai.application.project_access import list_my_projects as list_my_projects_service
from slow_ai.application.project_access import update_member_role as update_member_role_service


@frappe.whitelist()
def list_my_projects() -> dict:
    return list_my_projects_service()


@frappe.whitelist()
def list_members(project: str) -> dict:
    return list_members_service(project)


@frappe.whitelist()
def add_member(project: str, user: str, role: str) -> dict:
    return add_member_service(project, user, role)


@frappe.whitelist()
def update_member_role(member: str, role: str) -> dict:
    return update_member_role_service(member, role)


@frappe.whitelist()
def disable_member(member: str) -> dict:
    return disable_member_service(member)

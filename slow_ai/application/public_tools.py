"""Published template access for user-facing tool runs."""

from __future__ import annotations

from typing import Any

import frappe

from slow_ai.application.templates import create_workflow_from_template as create_template_workflow
from slow_ai.application.templates import get_template as get_template_service
from slow_ai.application.templates import list_templates as list_templates_service


def list_templates(category: str | None = None) -> dict[str, Any]:
    _require_logged_in_user()
    return list_templates_service(status="PUBLISHED", category=category)


def get_template(template: str) -> dict[str, Any]:
    _require_logged_in_user()
    payload = get_template_service(template)
    _assert_template_published(payload)
    return payload


def create_workflow_from_template(
    *,
    template: str,
    project: str,
    title: str | None = None,
) -> dict[str, Any]:
    _require_logged_in_user()
    payload = get_template_service(template)
    _assert_template_published(payload)
    _assert_project_access(project)
    return create_template_workflow(template=template, project=project, title=title)


def _require_logged_in_user() -> None:
    if frappe.session.user == "Guest":
        frappe.throw("Login is required to run Slow AI tools.", frappe.PermissionError)


def _assert_template_published(template: dict[str, Any]) -> None:
    if template.get("status") != "PUBLISHED":
        frappe.throw(
            f"Template is not published: {template.get('name') or ''}",
            frappe.PermissionError,
        )


def _assert_project_access(project: str) -> None:
    project_name = str(project or "").strip()
    if not project_name:
        frappe.throw("AI Project is required.", frappe.PermissionError)
    if not frappe.db.exists("AI Project", project_name):
        frappe.throw(f"AI Project does not exist: {project_name}.", frappe.PermissionError)
    if "System Manager" in frappe.get_roles():
        return
    owner = frappe.db.get_value("AI Project", project_name, "owner")
    if owner != frappe.session.user:
        frappe.throw(
            f"You do not have access to AI Project: {project_name}.",
            frappe.PermissionError,
        )

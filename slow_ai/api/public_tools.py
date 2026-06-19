"""Public Tool Run API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.public_tools import create_workflow_from_template as create_workflow_from_template_service
from slow_ai.application.public_tools import get_template as get_template_service
from slow_ai.application.public_tools import list_templates as list_templates_service


@frappe.whitelist()
def list_templates(category: str | None = None) -> dict:
    return list_templates_service(category=category)


@frappe.whitelist()
def get_template(template: str) -> dict:
    return get_template_service(template)


@frappe.whitelist()
def create_workflow_from_template(template: str, project: str, title: str | None = None) -> dict:
    return create_workflow_from_template_service(template=template, project=project, title=title)

"""Workflow template API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.templates import create_workflow_from_template as create_workflow_from_template_service
from slow_ai.application.templates import get_template as get_template_service
from slow_ai.application.templates import list_templates as list_templates_service
from slow_ai.application.templates import save_template as save_template_service


@frappe.whitelist()
def save_template(
    template_name: str,
    nodes,
    edges,
    layout=None,
    template: str | None = None,
    status: str = "DRAFT",
    category: str | None = None,
    description: str | None = None,
    preview_asset: str | None = None,
) -> dict:
    return save_template_service(
        template_name=template_name,
        nodes=nodes,
        edges=edges,
        layout=layout,
        template=template,
        status=status,
        category=category,
        description=description,
        preview_asset=preview_asset,
    )


@frappe.whitelist()
def get_template(template: str) -> dict:
    return get_template_service(template)


@frappe.whitelist()
def list_templates(status: str | None = None, category: str | None = None) -> dict:
    return list_templates_service(status=status, category=category)


@frappe.whitelist()
def create_workflow_from_template(template: str, project: str, title: str | None = None) -> dict:
    return create_workflow_from_template_service(template=template, project=project, title=title)

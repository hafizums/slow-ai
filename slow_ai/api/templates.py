"""Workflow template API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.templates import create_workflow_from_template as create_workflow_from_template_service
from slow_ai.application.templates import approve_template as approve_template_service
from slow_ai.application.templates import archive_template as archive_template_service
from slow_ai.application.templates import get_template as get_template_service
from slow_ai.application.templates import get_template_version as get_template_version_service
from slow_ai.application.templates import list_templates as list_templates_service
from slow_ai.application.templates import list_template_versions as list_template_versions_service
from slow_ai.application.templates import reject_template as reject_template_service
from slow_ai.application.templates import rollback_template_to_version as rollback_template_to_version_service
from slow_ai.application.templates import save_template as save_template_service
from slow_ai.application.templates import submit_template_for_review as submit_template_for_review_service


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
    input_schema=None,
    input_schema_json=None,
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
        input_schema=input_schema,
        input_schema_json=input_schema_json,
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


@frappe.whitelist()
def submit_template_for_review(template: str) -> dict:
    return submit_template_for_review_service(template=template)


@frappe.whitelist()
def approve_template(template: str, review_notes: str | None = None) -> dict:
    return approve_template_service(template=template, review_notes=review_notes)


@frappe.whitelist()
def reject_template(template: str, rejection_reason: str) -> dict:
    return reject_template_service(template=template, rejection_reason=rejection_reason)


@frappe.whitelist()
def archive_template(template: str, reason: str | None = None) -> dict:
    return archive_template_service(template=template, reason=reason)


@frappe.whitelist()
def list_template_versions(template: str) -> dict:
    return list_template_versions_service(template=template)


@frappe.whitelist()
def get_template_version(template_version: str) -> dict:
    return get_template_version_service(template_version=template_version)


@frappe.whitelist()
def rollback_template_to_version(template: str, template_version: str, review_notes: str | None = None) -> dict:
    return rollback_template_to_version_service(
        template=template,
        template_version=template_version,
        review_notes=review_notes,
    )

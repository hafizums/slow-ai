"""Safe template-version lineage helpers."""

from __future__ import annotations

from typing import Any

import frappe


SAFE_TEMPLATE_VERSION_FIELDS = [
    "name",
    "template",
    "version_no",
    "template_name",
    "category",
    "description",
    "snapshot_hash",
]


def assert_valid_template_lineage(source_template: str | None, source_template_version: str | None) -> None:
    template = str(source_template or "").strip()
    version = str(source_template_version or "").strip()
    if not template and not version:
        return
    if not template or not version:
        frappe.throw("Template lineage requires both source_template and source_template_version.", frappe.ValidationError)
    if not frappe.db.exists("AI Workflow Template", template):
        frappe.throw(f"Source template does not exist: {template}.", frappe.ValidationError)
    row = frappe.db.get_value("AI Workflow Template Version", version, ["template"], as_dict=True)
    if not row:
        frappe.throw(f"Source template version does not exist: {version}.", frappe.ValidationError)
    if row.template != template:
        frappe.throw("Source template version does not belong to the source template.", frappe.ValidationError)


def safe_template_lineage(source_template: str | None, source_template_version: str | None) -> dict[str, Any] | None:
    template = str(source_template or "").strip()
    version = str(source_template_version or "").strip()
    if not template and not version:
        return None

    lineage: dict[str, Any] = {
        "source_template": template or None,
        "source_template_version": version or None,
    }
    if version:
        row = frappe.db.get_value(
            "AI Workflow Template Version",
            version,
            SAFE_TEMPLATE_VERSION_FIELDS,
            as_dict=True,
        )
        if row:
            lineage.update(
                {
                    "source_template": row.template,
                    "source_template_version": row.name,
                    "version_no": row.version_no,
                    "snapshot_hash": row.snapshot_hash,
                    "template_name": row.template_name,
                    "category": row.category,
                    "description": row.description,
                }
            )
            return lineage

    if template:
        template_name = frappe.db.get_value("AI Workflow Template", template, "template_name")
        if template_name:
            lineage["template_name"] = template_name
    return lineage

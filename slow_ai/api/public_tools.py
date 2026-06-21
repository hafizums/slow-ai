"""Public Tool Run API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.public_tools import cleanup_stale_tool_drafts as cleanup_stale_tool_drafts_service
from slow_ai.application.public_tools import create_run_share as create_run_share_service
from slow_ai.application.public_tools import create_workflow_from_template as create_workflow_from_template_service
from slow_ai.application.public_tools import archive_my_run as archive_my_run_service
from slow_ai.application.public_tools import cancel_my_run as cancel_my_run_service
from slow_ai.application.public_tools import disable_run_share as disable_run_share_service
from slow_ai.application.public_tools import get_my_run as get_my_run_service
from slow_ai.application.public_tools import get_run_output_gallery as get_run_output_gallery_service
from slow_ai.application.public_tools import get_shared_run as get_shared_run_service
from slow_ai.application.public_tools import get_template as get_template_service
from slow_ai.application.public_tools import list_my_runs as list_my_runs_service
from slow_ai.application.public_tools import list_templates as list_templates_service
from slow_ai.application.public_tools import prepare_rerun_from_run as prepare_rerun_from_run_service
from slow_ai.application.public_tools import prepare_workflow_from_template as prepare_workflow_from_template_service
from slow_ai.application.public_tools import update_rerun_draft_values as update_rerun_draft_values_service


@frappe.whitelist()
def list_templates(category: str | None = None) -> dict:
    return list_templates_service(category=category)


@frappe.whitelist()
def get_template(template: str) -> dict:
    return get_template_service(template)


@frappe.whitelist()
def create_workflow_from_template(template: str, project: str, title: str | None = None) -> dict:
    return create_workflow_from_template_service(template=template, project=project, title=title)


@frappe.whitelist()
def prepare_workflow_from_template(template: str, project: str, title: str | None = None, values=None) -> dict:
    return prepare_workflow_from_template_service(template=template, project=project, title=title, values=values)


@frappe.whitelist()
def prepare_rerun_from_run(workflow_run: str, title: str | None = None) -> dict:
    return prepare_rerun_from_run_service(workflow_run=workflow_run, title=title)


@frappe.whitelist()
def update_rerun_draft_values(workflow: str, values=None) -> dict:
    return update_rerun_draft_values_service(workflow=workflow, values=values)


@frappe.whitelist()
def cleanup_stale_tool_drafts(max_age_hours: int | str | None = 24, limit: int | str = 100, dry_run=False) -> dict:
    return cleanup_stale_tool_drafts_service(max_age_hours=max_age_hours, limit=limit, dry_run=dry_run)


@frappe.whitelist()
def list_my_runs(project: str | None = None, limit: int | str = 50, include_archived: bool | str | int = False) -> dict:
    return list_my_runs_service(project=project, limit=limit, include_archived=include_archived)


@frappe.whitelist()
def get_my_run(workflow_run: str) -> dict:
    return get_my_run_service(workflow_run)


@frappe.whitelist()
def get_run_output_gallery(workflow_run: str) -> dict:
    return get_run_output_gallery_service(workflow_run)


@frappe.whitelist()
def cancel_my_run(workflow_run: str) -> dict:
    return cancel_my_run_service(workflow_run)


@frappe.whitelist()
def archive_my_run(workflow_run: str) -> dict:
    return archive_my_run_service(workflow_run)


@frappe.whitelist()
def create_run_share(workflow_run: str, selected_assets=None, expires_at: str | None = None) -> dict:
    return create_run_share_service(workflow_run=workflow_run, selected_assets=selected_assets, expires_at=expires_at)


@frappe.whitelist()
def disable_run_share(share_token: str | None = None, share: str | None = None) -> dict:
    return disable_run_share_service(share_token=share_token, share=share)


@frappe.whitelist(allow_guest=True)
def get_shared_run(share_token: str) -> dict:
    return get_shared_run_service(share_token=share_token)

"""Read-only shared Tool Run page context."""

import frappe


no_cache = 1


def get_context(context):
    context.no_cache = 1
    context.share_token = frappe.form_dict.get("token") or ""
    context.title = "Shared Slow AI Run"

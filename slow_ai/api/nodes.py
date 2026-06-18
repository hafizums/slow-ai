"""Node metadata API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.node_catalog import get_object_info as get_object_info_service


@frappe.whitelist()
def get_object_info() -> dict:
    return get_object_info_service()

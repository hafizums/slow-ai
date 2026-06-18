"""Asset API methods."""

from __future__ import annotations

import frappe

from slow_ai.application.assets import upload as upload_service
from slow_ai.application.assets import view as view_service


@frappe.whitelist()
def upload(
    project: str,
    asset_type: str,
    url: str | None = None,
    file: str | None = None,
    mime_type: str | None = None,
    metadata=None,
) -> dict:
    return upload_service(
        project=project,
        asset_type=asset_type,
        url=url,
        file=file,
        mime_type=mime_type,
        metadata=metadata,
    )


@frappe.whitelist()
def view(asset: str) -> dict:
    return view_service(asset)

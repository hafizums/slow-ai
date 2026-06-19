"""Server-side Replicate credential lookup."""

from __future__ import annotations

import os

import frappe

from slow_ai.providers.replicate.errors import ReplicateAuthError
from slow_ai.providers.replicate.models import REPLICATE_PROVIDER_NAME


class ReplicateAuth:
    def get_api_key(self, provider_account_name: str | None = None) -> str:
        if provider_account_name:
            return self._get_account_secret(provider_account_name)

        default_account = frappe.get_all(
            "AI Provider Account",
            filters={
                "provider": REPLICATE_PROVIDER_NAME,
                "is_default": 1,
                "status": "ACTIVE",
            },
            fields=["name"],
            order_by="creation asc",
            limit=1,
        )
        if default_account:
            return self._get_account_secret(default_account[0].name)

        api_key = os.environ.get("REPLICATE_API_KEY") or os.environ.get("REPLICATE_API_TOKEN")
        if api_key:
            return api_key

        raise ReplicateAuthError("No active Replicate provider account or REPLICATE_API_KEY found.")

    def _get_account_secret(self, provider_account_name: str) -> str:
        account = frappe.get_doc("AI Provider Account", provider_account_name)
        if account.provider != REPLICATE_PROVIDER_NAME:
            raise ReplicateAuthError("Provider account is not a Replicate account.")
        if account.status != "ACTIVE":
            raise ReplicateAuthError("Replicate provider account is disabled.")

        api_key = account.get_password("api_key_secret")
        if not api_key:
            raise ReplicateAuthError("Replicate provider account does not contain an API key.")
        return api_key

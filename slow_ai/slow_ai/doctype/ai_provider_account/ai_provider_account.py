import json

import frappe
from frappe.model.document import Document


class AIProviderAccount(Document):
    def validate(self):
        self.provider = _clean_required(self.provider, "Provider")
        self.account_label = _clean_required(self.account_label, "Account Label")
        self.status = _clean_status(self.status)
        self.project = _clean_optional(self.project)
        self.user = _clean_optional(self.user)
        self._validate_json_object("rate_limit_json")

    def _validate_json_object(self, fieldname: str) -> None:
        value = self.get(fieldname)
        if not value:
            return
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            frappe.throw(f"{self.meta.get_label(fieldname)} must be valid JSON.")
        if not isinstance(parsed, dict):
            frappe.throw(f"{self.meta.get_label(fieldname)} must be a JSON object.")


def _clean_required(value, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        frappe.throw(f"{label} is required.")
    return cleaned


def _clean_optional(value) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _clean_status(value) -> str:
    status = str(value or "ACTIVE").strip().upper()
    if status not in {"ACTIVE", "DISABLED"}:
        frappe.throw("AI Provider Account status must be ACTIVE or DISABLED.")
    return status

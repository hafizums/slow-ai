"""AI Model persistence validation."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document


class AIModel(Document):
    def validate(self) -> None:
        self._normalize_values()
        self._validate_required_values()
        self._validate_status()
        self._validate_json_objects()
        self._validate_model_slug_unique()

    def _normalize_values(self) -> None:
        for fieldname in (
            "model_id",
            "model_slug",
            "model_name",
            "provider",
            "node_type",
            "category",
            "modality",
        ):
            value = self.get(fieldname)
            if isinstance(value, str):
                self.set(fieldname, value.strip())

        if not self.status:
            self.status = "ENABLED"
        if not self.model_slug:
            self.model_slug = self.model_id
        if not self.category:
            self.category = "provider"

    def _validate_required_values(self) -> None:
        for fieldname, label in (
            ("model_id", "Model ID / Provider Path"),
            ("model_name", "Display Name"),
            ("provider", "Provider"),
        ):
            if not self.get(fieldname):
                frappe.throw(_("{0} is required.").format(label), frappe.ValidationError)

    def _validate_status(self) -> None:
        if self.status not in {"ENABLED", "DISABLED"}:
            frappe.throw(_("AI Model status must be ENABLED or DISABLED."), frappe.ValidationError)

    def _validate_json_objects(self) -> None:
        for fieldname, label in (
            ("pricing_json", "Pricing JSON"),
            ("capabilities_json", "Capabilities JSON"),
            ("input_metadata_json", "Input Metadata JSON"),
            ("output_metadata_json", "Output Metadata JSON"),
        ):
            value = self.get(fieldname)
            if not value:
                continue
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                frappe.throw(_("{0} must be valid JSON.").format(label), frappe.ValidationError)
            if not isinstance(parsed, dict):
                frappe.throw(_("{0} must be a JSON object.").format(label), frappe.ValidationError)

    def _validate_model_slug_unique(self) -> None:
        if not self.model_slug:
            return
        filters = {"model_slug": self.model_slug}
        if self.name:
            filters["name"] = ["!=", self.name]
        duplicate = frappe.get_all("AI Model", filters=filters, pluck="name", limit=1)
        if duplicate:
            frappe.throw(
                _("AI Model slug {0} is already used by {1}.").format(self.model_slug, duplicate[0]),
                frappe.ValidationError,
            )

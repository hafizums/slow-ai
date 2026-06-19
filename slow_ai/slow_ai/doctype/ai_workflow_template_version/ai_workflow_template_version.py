import frappe
from frappe import _
from frappe.model.document import Document


IMMUTABLE_FIELDS = {
    "template",
    "version_no",
    "template_name",
    "category",
    "description",
    "preview_asset",
    "nodes_json",
    "edges_json",
    "layout_json",
    "input_schema_json",
    "snapshot_hash",
    "approved_by",
    "approved_at",
    "source_template_modified",
    "owner",
}


class AIWorkflowTemplateVersion(Document):
    def before_save(self):
        if self.is_new():
            return
        previous = frappe.get_doc(self.doctype, self.name)
        for fieldname in IMMUTABLE_FIELDS:
            if self.get(fieldname) != previous.get(fieldname):
                frappe.throw(_("AI Workflow Template Version content is immutable after creation."))


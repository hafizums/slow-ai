import frappe
from frappe import _
from frappe.model.document import Document


class AIWorkflowVersion(Document):
    def before_save(self):
        if not self.is_new():
            frappe.throw(_("AI Workflow Version is immutable after creation."))

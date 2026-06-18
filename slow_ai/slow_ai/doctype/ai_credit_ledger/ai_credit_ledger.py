import frappe
from frappe import _
from frappe.model.document import Document


class AICreditLedger(Document):
    def before_save(self):
        if not self.is_new():
            frappe.throw(_("AI Credit Ledger is append-only."))

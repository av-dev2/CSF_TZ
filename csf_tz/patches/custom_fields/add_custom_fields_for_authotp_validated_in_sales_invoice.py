import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def execute():
    fields={
        "Sales Invoice":[
            {
                "label":"AuthOTP Validated",
                "fieldname":"authotp_validated",
                "insert_after":"column_break_sn02w",
                "fieldtype":"Check",
                "read_only":1,
                "no_copy":1,
            }
        ]
    }
    create_custom_fields(fields, update=True)

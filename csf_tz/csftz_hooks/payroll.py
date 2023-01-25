from __future__ import unicode_literals
import frappe
from frappe import _
import frappe
import os
from frappe.utils.background_jobs import enqueue
from frappe.utils.pdf import get_pdf, cleanup
from PyPDF2 import PdfFileWriter
from csf_tz import console


@frappe.whitelist()
def update_slips(payroll_entry):
    ss_list = frappe.get_all("Salary Slip", filters={
                             "payroll_entry": payroll_entry})
    count = 0
    for salary in ss_list:
        ss_doc = frappe.get_doc("Salary Slip", salary.name)
        if ss_doc.docstatus != 0:
            continue
        ss_doc.earnings = []
        ss_doc.deductions = []
        ss_doc.queue_action("save", timeout=4600)
        count += 1

    frappe.msgprint(_("{0} Salary Slips is updated".format(count)))
    return count


@frappe.whitelist()
def update_slip(salary_slip):
    ss_doc = frappe.get_doc("Salary Slip", salary_slip)
    if ss_doc.docstatus != 0:
        return
    ss_doc.earnings = []
    ss_doc.deductions = []
    ss_doc.save()
    frappe.msgprint(_("Salary Slips is updated"))
    return "True"


@frappe.whitelist()
def print_slips(payroll_entry):
    enqueue(method=enqueue_print_slips, queue='short', timeout=100000,
            is_async=True, job_name="print_salary_slips", kwargs=payroll_entry)


def enqueue_print_slips(kwargs):
    console("Start Printing")
    payroll_entry = kwargs
    ss_data = frappe.get_all("Salary Slip", filters={
                             "payroll_entry": payroll_entry})
    ss_list = []
    for i in ss_data:
        ss_list.append(i.name)
    doctype = dict(
        {"Salary Slip": ss_list}
    )
    print_format = ""
    default_print_format = frappe.db.get_value('Property Setter', dict(
        property='default_print_format', doc_type="Salary Slip"), "value")
    if default_print_format:
        print_format = default_print_format
    else:
        print_format = "Standard"

    pdf = download_multi_pdf(doctype, payroll_entry,
                             format=print_format, no_letterhead=0)
    if pdf:
        ret = frappe.get_doc({
            "doctype": "File",
            "attached_to_doctype": "Payroll Entry",
            "attached_to_name": payroll_entry,
            "folder": "Home/Attachments",
            "file_name": payroll_entry + ".pdf",
            "file_url": "/files/" + payroll_entry + ".pdf",
            "content": pdf
        })
        ret.save(ignore_permissions=1)
        console("Printing Finished", "The PDF file is ready in attatchments")
        return ret


def download_multi_pdf(doctype, name, format=None, no_letterhead=0):
    output = PdfFileWriter()
    if isinstance(doctype, dict):
        for doctype_name in doctype:
            for doc_name in doctype[doctype_name]:
                try:
                    console(doc_name)
                    output = frappe.get_print(
                        doctype_name, doc_name, format, as_pdf=True, output=output, no_letterhead=no_letterhead)
                except Exception:
                    frappe.log_error("Permission Error on doc {} of doctype {}".format(
                        doc_name, doctype_name))
        frappe.local.response.filename = "{}.pdf".format(name)

    return read_multi_pdf(output)


def read_multi_pdf(output):
    fname = os.path.join(
        "/tmp", "frappe-pdf-{0}.pdf".format(frappe.generate_hash()))
    output.write(open(fname, "wb"))

    with open(fname, "rb") as fileobj:
        filedata = fileobj.read()

    return filedata

@frappe.whitelist()
def create_journal_entry(payroll_entry):
    payroll_entry_doc = frappe.get_doc("Payroll Entry", payroll_entry)
    if payroll_entry_doc.docstatus != 1 or payroll_entry_doc.salary_slips_submitted == 1:
        return
    draft_slips_count = frappe.db.count("Salary Slip", filters={
                             "payroll_entry": payroll_entry, "docstatus": 0})

    if draft_slips_count > 0:
        frappe.throw(_("Salary Slips are not submitted"))
    else:
        jv_name = payroll_entry_doc.make_accrual_jv_entry()
        jv_url = frappe.utils.get_url_to_form("Journal Entry", jv_name)
        si_msgprint = _("Journal Entry Created <a href='{0}'>{1}</a>").format(jv_url,jv_name)
        frappe.msgprint(si_msgprint)
        return "True"
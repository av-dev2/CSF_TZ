import frappe

try:
    from hrms.payroll.doctype.salary_slip.salary_slip import (
        SalarySlip as _SalarySlip,
    )  # version-14

except ImportError:
    from erpnext.payroll.doctype.salary_slip.salary_slip import (
        SalarySlip as _SalarySlip,
    )  # version-13


class SalarySlip(_SalarySlip):
    def get_working_days_details(self, *args, **kwargs):
        result = super().get_working_days_details(*args, **kwargs)

        fixed_working_days = get_fixed_working_days()
        if fixed_working_days is None:
            return result

        self.total_working_days = min(fixed_working_days, self.total_working_days)
        self.payment_days = min(fixed_working_days, self.payment_days)
        return result

    def calculate_lwp_or_ppl_based_on_leave_application(self, holidays, working_days, *args, **kwargs):
        fixed_working_days = get_fixed_working_days()
        if fixed_working_days is not None:
            working_days = min(fixed_working_days, working_days)

        return super().calculate_lwp_or_ppl_based_on_leave_application(holidays, working_days, *args, **kwargs)

    def get_payment_days(self, *args, **kwargs):
        fixed_working_days = get_fixed_working_days()
        if fixed_working_days is None:
            return super().get_payment_days(*args, **kwargs)

        self.total_working_days = min(fixed_working_days, self.total_working_days)
        payment_days = super().get_payment_days(*args, **kwargs)
        return min(fixed_working_days, payment_days)


def get_fixed_working_days():
    csf_tz_settings = frappe.get_cached_doc("CSF TZ Settings", "CSF TZ Settings")
    if csf_tz_settings.enable_fixed_working_days_per_month:
        return csf_tz_settings.working_days_per_month

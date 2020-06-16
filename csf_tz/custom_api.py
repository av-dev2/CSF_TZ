from __future__ import unicode_literals
from frappe.utils import flt
from erpnext.setup.utils import get_exchange_rate
import frappe
from frappe import _
import frappe.permissions
import frappe.share
import traceback
from frappe.utils import flt, cint, getdate
from frappe.model.mapper import get_mapped_doc
# # from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_delivery_note

@frappe.whitelist()
def app_error_log(title,error):
	d = frappe.get_doc({
			"doctype": "Custom Error Log",
			"title":str("User:")+str(title),
			"error":traceback.format_exc()
		})
	d = d.insert(ignore_permissions=True)
	return d	

@frappe.whitelist()
def getInvoiceExchangeRate(date,currency):
	try:
		exchange_rate = get_exchange_rate(currency,frappe.defaults.get_global_default("currency"),str(date))
		return exchange_rate

	except Exception as e:
		error_log = app_error_log(frappe.session.user,str(e))


@frappe.whitelist()
def getInvoice(currency,name):
	try:
		sinv_details = frappe.get_all("Sales Invoice",filters = [["Sales Invoice","currency","=",str(currency)],["Sales Invoice","status","in",["Unpaid","Overdue"]]],fields = ["name","grand_total","conversion_rate","currency"])
		pinv_details = frappe.get_all("Purchase Invoice",filters = [["Purchase Invoice","currency","=",str(currency)],["Purchase Invoice","status","in",["Unpaid","Overdue"]]],fields = ["name","grand_total","conversion_rate","currency"])
		doc = frappe.get_doc("Open Invoice Exchange Rate Revaluation",name)
		doc.inv_err_detail = []
		doc.save()
		if sinv_details:
			count = 1
			for sinv in sinv_details:
				if not flt(sinv.conversion_rate) == flt(doc.exchange_rate_to_company_currency):
					addChildItem(name,sinv.name,'Sales Invoice',sinv.conversion_rate,sinv.currency,sinv.grand_total,doc.exchange_rate_to_company_currency,count)
					count += 1
		if pinv_details:
			for pinv in pinv_details:
				if not flt(pinv.conversion_rate) == flt(doc.exchange_rate_to_company_currency):
					addChildItem(name,pinv.name,'Purchase Invoice',pinv.conversion_rate,pinv.currency,pinv.grand_total,doc.exchange_rate_to_company_currency,count)
					count += 1
		return sinv_details

	except Exception as e:
		error_log = app_error_log(frappe.session.user,str(e))


def addChildItem(name,inv_no,invoice_type,invoice_exchange_rate,invoice_currency,invoice_amount,current_exchange,idx):
	gain_loss = (flt(invoice_amount) * flt(invoice_exchange_rate))-(flt(invoice_amount) * flt(current_exchange))
	child_doc = frappe.get_doc(dict(
		doctype = "Inv ERR Detail",
		parent = name,
		parenttype = "Open Invoice Exchange Rate Revaluation",
		parentfield = "inv_err_detail",
		invoice_number = inv_no,
		invoice_type = invoice_type,
		invoice_exchange_rate = invoice_exchange_rate,
		invoice_currency = invoice_currency,
		invoice_gain_or_loss = gain_loss,
		invoice_amount = invoice_amount,
		idx = idx
	)).insert()


@frappe.whitelist()
def print_out(message, alert= False, add_traceback=False, to_error_log=False ):
	if not message:
		return	
	
	def out(mssg):
		if message:
			frappe.errprint(str(mssg))
			if to_error_log:
				frappe.log_error(str(mssg))
			if add_traceback:
				if len(frappe.utils.get_traceback()) > 20:
					frappe.errprint(frappe.utils.get_traceback())
			if alert:
				frappe.msgprint(str(mssg))

	def check_msg(msg):
		if isinstance(msg, str):
			msg = str(msg)

		elif isinstance(msg, int):
			msg = str(msg)

		elif isinstance(msg, float):
			msg = str(msg)

		elif isinstance(msg, dict):
			msg = frappe._dict(msg)
			
		elif isinstance(msg, list):
			for item in msg:
				check_msg(item)
			msg = ""

		elif isinstance(msg, object):
			msg = str(msg.__dict__)
		
		else:
			msg = str(msg)
		out(msg)
	check_msg(message)



def get_stock_ledger_entries(item_code):
	conditions = " and item_code = '%s'" % item_code
	return frappe.db.sql("""
		select item_code, batch_no, warehouse, sum(actual_qty) as actual_qty
		from `tabStock Ledger Entry`
		where docstatus < 2  %s
		group by voucher_no, batch_no, item_code, warehouse
		order by item_code, warehouse""" %
		conditions, as_dict=1)


@frappe.whitelist()
def get_item_info(item_code):

	sle = get_stock_ledger_entries(item_code)
	iwb_map = {}
	float_precision = cint(frappe.db.get_default("float_precision")) or 3

	for d in sle:
		iwb_map.setdefault(d.item_code, {}).setdefault(d.warehouse, {})\
			.setdefault(d.batch_no, frappe._dict({
				 "bal_qty": 0.0
			}))
		qty_dict = iwb_map[d.item_code][d.warehouse][d.batch_no]

		expiry_date_unicode = frappe.db.get_value('Batch', d.batch_no, 'expiry_date')
		
		if expiry_date_unicode:	
			qty_dict.expires_on = expiry_date_unicode
			exp_date = frappe.utils.data.getdate(expiry_date_unicode)
			qty_dict.expires_on = exp_date
			expires_in_days = (exp_date - frappe.utils.datetime.date.today()).days
			if expires_in_days > 0:
				qty_dict.expiry_status = expires_in_days
			else:
				qty_dict.expiry_status = 0

		qty_dict.actual_qty = flt(qty_dict.actual_qty, float_precision) + flt(d.actual_qty, float_precision)

	iwd_list = []
	for key1,value1 in iwb_map.items():
		for key2,value2 in value1.items():
			for key3,value3 in value2.items():
				lin_dict = {
					"item_code"	: key1,
					"warehouse"	: key2,
					"batch_no"	: key3
				}
				lin_dict.update(value3)
				iwd_list.append(lin_dict)

	return iwd_list


@frappe.whitelist()
def get_item_prices(item_code,currency,customer=None,company=None):
	item_code = "'{0}'".format(item_code)
	currency = "'{0}'".format(currency)
	unique_records = int(frappe.db.get_value('CSF TZ Settings', None, 'unique_records'))
	prices_list= []
	unique_price_list = []
	max_records = frappe.db.get_value('Company', company, 'max_records_in_dialog') or 20
	if customer:
		conditions = " and SI.customer = '%s'" % customer
	else:
		conditions = ""

	query = """ SELECT SI.name, SI.posting_date, SI.customer, SIT.item_code, SIT.qty, SIT.rate
            FROM `tabSales Invoice` AS SI 
            INNER JOIN `tabSales Invoice Item` AS SIT ON SIT.parent = SI.name
            WHERE 
                SIT.item_code = {0} 
                AND SIT.parent = SI.name
                AND SI.docstatus=%s 
                AND SI.currency = {2}
                AND SI.is_return != 1
                AND SI.company = '{3}'
                {1}
            ORDER by SI.posting_date DESC""".format(item_code,conditions,currency,company) % (1)

	items = frappe.db.sql(query,as_dict=True)
	for item in items:
		item_dict = {
					"name": item.item_code,
					"item_code" : item.item_code,
					"price" : item.rate,
					"date" : item.posting_date,
					"invoice" : item.name,
					"customer": item.customer,
					"qty" : item.qty,
				}
		if unique_records == 1 and item.rate not in unique_price_list and len(prices_list) <= max_records: 
			unique_price_list.append(item.rate)
			prices_list.append(item_dict)
		elif unique_records != 1 and  item.rate and len(prices_list) <= max_records:
			prices_list.append(item_dict)
	return prices_list



@frappe.whitelist()
def get_item_prices_custom(*args):
	# print_out(str(args))
	filters = args[5]
	start = args[3]
	limit = args[4]
	unique_records = int(frappe.db.get_value('CSF TZ Settings', None, 'unique_records'))
	if "customer" in filters:
		customer = filters["customer"]
	else:
		customer = ""
	company = filters["company"]
	item_code = "'{0}'".format(filters["item_code"])
	currency = "'{0}'".format(filters["currency"])
	prices_list= []
	unique_price_list = []
	max_records =  int(start) + int(limit)
	conditions = ""
	if "posting_date" in filters:
		posting_date = filters["posting_date"]
		from_date="'{from_date}'".format(from_date=posting_date[1][0])
		to_date = "'{to_date}'".format(to_date=posting_date[1][1])
		conditions += "AND DATE(SI.posting_date) BETWEEN {start} AND {end}".format(start=from_date,end=to_date)
	if customer:
		conditions += " AND SI.customer = '%s'" % customer

	query = """ SELECT SI.name, SI.posting_date, SI.customer, SIT.item_code, SIT.qty,  SIT.rate
            FROM `tabSales Invoice` AS SI 
            INNER JOIN `tabSales Invoice Item` AS SIT ON SIT.parent = SI.name
            WHERE 
                SIT.item_code = {0} 
                AND SIT.parent = SI.name
                AND SI.docstatus= 1
                AND SI.currency = {2}
                AND SI.is_return != 1
                AND SI.company = '{3}'
                {1}
            ORDER by SI.posting_date DESC""".format(item_code,conditions,currency,company) 

	items = frappe.db.sql(query,as_dict=True)
	for item in items:
		item_dict = {
					"name": item.item_code,
					"item_code" : item.item_code,
					"rate" : item.rate,
					"posting_date" : item.posting_date,
					"invoice" : item.name,
					"customer": item.customer,
					"qty" : item.qty,
				}
		if unique_records == 1 and item.rate not in unique_price_list and len(prices_list) <= max_records: 
			unique_price_list.append(item.rate)
			prices_list.append(item_dict)
		elif unique_records != 1 and  item.rate and len(prices_list) <= max_records:
			prices_list.append(item_dict)			
	return prices_list


@frappe.whitelist()
def get_repack_template(template_name,qty):
	template_doc = frappe.get_doc("Repack Template",template_name)
	rows = []
	rows.append({
		"item_code" : template_doc.item_code,
		"item_uom": template_doc.item_uom,
		"qty": cint(qty),
		"item_template" : 1 ,

	})
	for i in template_doc.repack_template_details:
		rows.append({
			"item_code" : i.item_code,
			"item_uom": i.item_uom,
			"qty": cint(float(i.qty / template_doc.qty) * float(qty)),
			"item_template" : 0 ,
		})
	return rows

def create_delivery_note(doc,method):
	if doc.update_stock:
		return
	from_delivery_note = False
	i = 0
	warehouses_list =[]
	for item in doc.items:
		if item.warehouse not in warehouses_list:
			warehouses_list.append(item.warehouse)
		if item.delivery_note or item.delivered_by_supplier:
			from_delivery_note = True
		if check_item_is_maintain(item.item_code):
			i += 1

	if from_delivery_note or i == 0:
		return
		
	for warehouse in warehouses_list:
		delivery_doc = frappe.get_doc(make_delivery_note(doc.name,warehouse))
		delivery_doc.flags.ignore_permissions = True
		delivery_doc.flags.ignore_account_permission = True
		delivery_doc.save()
		# delivery_doc.submit()
		url = frappe.utils.get_url_to_form(delivery_doc.doctype, delivery_doc.name)
		msgprint = "Delivery Note Created as Draft at <a href='{0}'>{1}</a>".format(url,delivery_doc.name)
		frappe.msgprint(_(msgprint))



def check_item_is_maintain(item_name):
		is_stock_item = frappe.get_value("Item",item_name,"is_stock_item")
		if is_stock_item != 1:
			return False
		else:
			return True
	


def make_delivery_note(source_name, warehouse, target_doc=None):
	def set_missing_values(source, target):
		target.ignore_pricing_rule = 1
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	def update_item(source_doc, target_doc, source_parent):
		target_doc.qty = flt(source_doc.qty) - flt(source_doc.delivered_qty)
		target_doc.stock_qty = target_doc.qty * flt(source_doc.conversion_factor)

		target_doc.base_amount = target_doc.qty * flt(source_doc.base_rate)
		target_doc.amount = target_doc.qty * flt(source_doc.rate)


	doclist = get_mapped_doc("Sales Invoice", source_name, 	{
		"Sales Invoice": {
			"doctype": "Delivery Note",
			"validation": {
				"docstatus": ["=", 1]
			}
		},
		"Sales Invoice Item": {
			"doctype": "Delivery Note Item",
			"field_map": {
				"name": "si_detail",
				"parent": "against_sales_invoice",
				"serial_no": "serial_no",
				"sales_order": "against_sales_order",
				"so_detail": "so_detail",
				"cost_center": "cost_center",
				"Warehouse":"warehouse",
			},
			"postprocess": update_item,
			"condition": lambda doc: check_item_is_maintain(doc.item_code),
			"condition": lambda doc: doc.warehouse == warehouse,
			# "condition": lambda doc: doc.delivered_by_supplier!=1,
			
		},
		"Sales Taxes and Charges": {
			"doctype": "Sales Taxes and Charges",
			"add_if_empty": True
		},
		"Sales Team": {
			"doctype": "Sales Team",
			"field_map": {
				"incentives": "incentives"
			},
			"add_if_empty": True
		}
	}, target_doc, set_missing_values)

	return doclist



def create_indirect_expense_item(doc,method=None):
	if not "Indirect Expenses" in doc.parent_account and doc.item:
		doc.item = ""
		return
	if not "Indirect Expenses" in doc.parent_account:
		return 
	item = frappe.get_value("Item", doc.name, "name")
	if item:
		doc.item = item
		return item
	new_item = frappe.get_doc(dict(
		doctype = "Item",
		item_code = doc.name,
		item_group = "Indirect Expenses",
		enable_deferred_expense = 1,
		is_stock_item = 0,
		include_item_in_manufacturing = 0,
		deferred_expense_account = doc.name,
	))
	new_item.flags.ignore_permissions = True
	frappe.flags.ignore_account_permission = True
	new_item.save()
	if new_item.name:
		url = frappe.utils.get_url_to_form(new_item.doctype, new_item.name)
		msgprint = "New Item is Created <a href='{0}'>{1}</a>".format(url,new_item.name)
		frappe.msgprint(_(msgprint))
		doc.item = new_item.name
	return new_item.name


@frappe.whitelist()
def add_indirect_expense_item(account_name):
	account = frappe.get_doc("Account", account_name)
	return create_indirect_expense_item(account) 
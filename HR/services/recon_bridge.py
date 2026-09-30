"""Bridge to the fuel-station reconciliation system — NOT connected in Rehumile.

The HR app was built alongside a till/petty-cash reconciliation system. Rehumile TMW has no such system, so this
module keeps the same function names (so the rest of the HR code is unchanged) but never writes anywhere:

  * lookups return "nothing found" (nobody is matched, no tills / petty-cash funds exist)
  * anything that would post a cash record raises ReconError with a clear message

Salary figures reach Rehumile's finance numbers through the payroll module (Finance dashboard), not through here.
"""
from decimal import Decimal


class ReconError(Exception):
    pass


_MSG = "The till / petty-cash reconciliation system is not connected to Rehumile, so no cash record was posted."


def category(name):
    return None


def open_till_shifts():
    return []


def petty_funds():
    return []


def post_till_outflow(shift_id, amount, description, user, cat_name):
    raise ReconError(_MSG)


def post_bank_outflow(amount, description, user, cat_name, day=None):
    raise ReconError(_MSG)


def post_petty_outflow(fund_id, amount, description, user):
    raise ReconError(_MSG)


def post_till_inflow(shift_id, amount, description, user, cat_name):
    raise ReconError(_MSG)


def post_petty_inflow(fund_id, amount, description, user):
    raise ReconError(_MSG)


def salaries_expense(key_desc, amount, day, user, cat_name, existing_id=None):
    raise ReconError(_MSG)


def expense_amount(expense_id):
    return None


def existing_salary_total(cat_name, start, end, exclude_ids=()):
    return Decimal('0')


def find_person(employee_number):
    return None

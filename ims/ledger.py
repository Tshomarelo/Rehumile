"""
Double-entry accounting engine.

This module is the ONLY place that should ever create LedgerTransaction /
LedgerEntry rows. Every existing UI action (mark an invoice paid, log an
expense, run payroll, log a cash sale) calls one of the `post_*` functions
below — the person using the app never has to think about debits/credits.

Every posting is looked up by Account.system_key, never by name/code, so
renaming an account in the Chart of Accounts UI can never break posting.
"""
from decimal import Decimal

from django.db import transaction as db_transaction

from .models import Account, LedgerTransaction, LedgerEntry


# ─────────────────────────────────────────────────────────────────────────────
# Chart of Accounts seed data
# ─────────────────────────────────────────────────────────────────────────────

SEED_ACCOUNTS = [
    # code, system_key, name, account_type, account_subtype, normal_balance
    ('1000', 'BANK_CASH', 'Bank & Cash', 'asset', 'current_asset', 'debit'),
    ('1100', 'ACCOUNTS_RECEIVABLE', 'Accounts Receivable (Debtors)', 'asset', 'current_asset', 'debit'),
    ('1200', 'INVENTORY', 'Inventory / Stock on Hand', 'asset', 'current_asset', 'debit'),
    ('1500', 'FIXED_ASSETS', 'Fixed Assets (Lab Equipment & Tools)', 'asset', 'fixed_asset', 'debit'),
    ('1510', 'VAT_INPUT', 'VAT Input (Claimable)', 'asset', 'current_asset', 'debit'),

    ('2000', 'ACCOUNTS_PAYABLE', 'Accounts Payable (Creditors)', 'liability', 'current_liability', 'credit'),
    ('2100', 'VAT_PAYABLE', 'VAT Payable (Output)', 'liability', 'current_liability', 'credit'),
    ('2200', 'PAYE_UIF_PAYABLE', 'PAYE & UIF Payable', 'liability', 'current_liability', 'credit'),

    ('3000', 'OWNERS_EQUITY', "Owner's Equity / Capital", 'equity', '', 'credit'),
    ('3100', 'RETAINED_EARNINGS', 'Retained Earnings', 'equity', '', 'credit'),
    ('3200', 'OWNERS_DRAWINGS', "Owner's Drawings", 'equity', '', 'debit'),

    ('4000', 'REV_WIFI', 'WiFi Subscription Revenue', 'revenue', '', 'credit'),
    ('4100', 'REV_SLA', 'SLA Retainer Revenue', 'revenue', '', 'credit'),
    ('4200', 'REV_ADHOC', 'Ad-Hoc / Project Revenue', 'revenue', '', 'credit'),
    ('4300', 'REV_RETAIL', 'Retail / POS Sales Revenue', 'revenue', '', 'credit'),
    ('4400', 'REV_VOUCHER', 'Voucher Sales Revenue', 'revenue', '', 'credit'),

    ('5000', 'COGS_HARDWARE', 'Cost of Goods Sold — Hardware/Parts', 'expense', 'cogs', 'debit'),
    ('5100', 'COGS_AXXESS', 'Cost of Goods Sold — Axxess Wholesale', 'expense', 'cogs', 'debit'),

    ('6000', 'OPEX_RENT', 'Rent Expense', 'expense', 'operating_expense', 'debit'),
    ('6100', 'OPEX_UTILITIES', 'Utilities / Internet Expense', 'expense', 'operating_expense', 'debit'),
    ('6200', 'OPEX_BANKFEES', 'Bank Fees Expense', 'expense', 'operating_expense', 'debit'),
    ('6300', 'OPEX_SALARIES', 'Salaries & Wages Expense', 'expense', 'operating_expense', 'debit'),
    ('6400', 'OPEX_PAYE_UIF_EMPLOYER', 'PAYE/UIF Employer Contribution Expense', 'expense', 'operating_expense', 'debit'),
    ('6500', 'OPEX_MARKETING', 'Marketing Expense', 'expense', 'operating_expense', 'debit'),
    ('6600', 'OPEX_DEPRECIATION', 'Depreciation Expense', 'expense', 'operating_expense', 'debit'),
    ('6900', 'OPEX_OTHER', 'Other Operating Expense', 'expense', 'operating_expense', 'debit'),
]

INVOICE_TYPE_REVENUE_KEY = {
    'wifi': 'REV_WIFI',
    'sla': 'REV_SLA',
    'callout': 'REV_SLA',
    'adhoc': 'REV_ADHOC',
}


def seed_chart_of_accounts():
    """Idempotent — safe to call every time the app starts or the backfill command runs."""
    created = 0
    for code, system_key, name, account_type, account_subtype, normal_balance in SEED_ACCOUNTS:
        _, was_created = Account.objects.get_or_create(
            system_key=system_key,
            defaults=dict(
                code=code, name=name, account_type=account_type,
                account_subtype=account_subtype, normal_balance=normal_balance,
                is_system=True,
            ),
        )
        if was_created:
            created += 1
    return created


def account(system_key):
    return Account.objects.get(system_key=system_key)


# ─────────────────────────────────────────────────────────────────────────────
# Core posting primitive
# ─────────────────────────────────────────────────────────────────────────────

class UnbalancedTransactionError(Exception):
    pass


@db_transaction.atomic
def post_transaction(source_model, source_id, transaction_date, description, lines,
                      *, cash_flow_stream=None, user=None):
    """
    `lines` is a list of (system_key, debit, credit, memo) tuples.
    Idempotent: if a LedgerTransaction already exists for this
    (source_model, source_id), this is a no-op and returns None.
    """
    source_id = str(source_id)
    if LedgerTransaction.objects.filter(source_model=source_model, source_id=source_id).exists():
        return None

    total_debit = sum((Decimal(str(d)) for _, d, _, _ in lines), Decimal('0'))
    total_credit = sum((Decimal(str(c)) for _, _, c, _ in lines), Decimal('0'))
    if total_debit != total_credit:
        raise UnbalancedTransactionError(
            f"{source_model}:{source_id} — debits {total_debit} != credits {total_credit}"
        )
    if total_debit == 0:
        return None

    txn = LedgerTransaction.objects.create(
        transaction_date=transaction_date,
        description=description,
        source_model=source_model,
        source_id=source_id,
        cash_flow_stream=cash_flow_stream,
        created_by=user if user and getattr(user, 'is_authenticated', False) else None,
    )
    LedgerEntry.objects.bulk_create([
        LedgerEntry(
            transaction=txn,
            account=account(system_key),
            debit=Decimal(str(debit)),
            credit=Decimal(str(credit)),
            memo=memo,
        )
        for system_key, debit, credit, memo in lines
        if Decimal(str(debit)) != 0 or Decimal(str(credit)) != 0
    ])
    return txn


# ─────────────────────────────────────────────────────────────────────────────
# Business-event posting functions — call these from views, never build
# LedgerTransaction/LedgerEntry rows directly anywhere else.
# ─────────────────────────────────────────────────────────────────────────────

def post_invoice_sent(invoice, user=None):
    """Revenue recognition when an invoice is sent to the client (accrual basis)."""
    revenue_key = INVOICE_TYPE_REVENUE_KEY.get(invoice.invoice_type, 'REV_ADHOC')
    subtotal = Decimal(invoice.subtotal or 0)
    tax_amount = Decimal(invoice.tax_amount or 0)
    total = Decimal(invoice.total_amount or 0)
    if total <= 0:
        return None

    lines = [
        ('ACCOUNTS_RECEIVABLE', total, Decimal('0'), f"Invoice {invoice.invoice_number}"),
        (revenue_key, Decimal('0'), subtotal, f"Invoice {invoice.invoice_number}"),
    ]
    if tax_amount > 0:
        lines.append(('VAT_PAYABLE', Decimal('0'), tax_amount, f"Invoice {invoice.invoice_number}"))

    wholesale_cost = Decimal(invoice.wholesale_cost or 0)
    if invoice.invoice_type == 'wifi' and wholesale_cost > 0:
        lines.append(('COGS_AXXESS', wholesale_cost, Decimal('0'), f"Axxess cost — {invoice.invoice_number}"))
        lines.append(('ACCOUNTS_PAYABLE', Decimal('0'), wholesale_cost, f"Axxess cost — {invoice.invoice_number}"))

    return post_transaction(
        'Invoice', invoice.id,
        invoice.sent_at.date() if invoice.sent_at else (invoice.created_at.date() if invoice.created_at else invoice.billing_period_start),
        f"Invoice {invoice.invoice_number} sent",
        lines, user=user,
    )


def post_invoice_paid(invoice, user=None):
    """Clears the debtor when a client pays. Cash-basis fallback: if the
    'sent' entry was never posted (e.g. invoice created already-paid), this
    still posts the full revenue-recognition entry first."""
    if not LedgerTransaction.objects.filter(source_model='Invoice', source_id=str(invoice.id)).exists():
        post_invoice_sent(invoice, user)

    total = Decimal(invoice.total_amount or 0)
    if total <= 0:
        return None
    pay_date = invoice.payment_date or invoice.updated_at.date()
    return post_transaction(
        'InvoicePayment', invoice.id, pay_date,
        f"Payment received for invoice {invoice.invoice_number}",
        [
            ('BANK_CASH', total, Decimal('0'), f"Invoice {invoice.invoice_number}"),
            ('ACCOUNTS_RECEIVABLE', Decimal('0'), total, f"Invoice {invoice.invoice_number}"),
        ],
        cash_flow_stream='ocf', user=user,
    )


def post_expense(expense):
    amount = Decimal(expense.amount or 0)
    if amount <= 0:
        return None
    contra_key = 'BANK_CASH' if expense.payment_status == 'paid' else 'ACCOUNTS_PAYABLE'
    return post_transaction(
        'Expense', expense.id, expense.expense_date,
        f"{expense.vendor} — {expense.description or expense.category}",
        [
            (expense.account.system_key, amount, Decimal('0'), expense.vendor),
            (contra_key, Decimal('0'), amount, expense.vendor),
        ],
        cash_flow_stream=expense.cash_flow_stream if expense.payment_status == 'paid' else None,
        user=expense.recorded_by,
    )


def post_payroll_entry(entry):
    gross = Decimal(entry.total_gross or entry.gross_salary or 0)
    paye = Decimal(entry.paye_amount or 0)
    uif_employee = Decimal(entry.uif_employee or 0)
    uif_employer = Decimal(entry.uif_employer or 0)
    net_pay = Decimal(entry.net_pay or 0)
    if gross <= 0:
        return None

    lines = [
        ('OPEX_SALARIES', gross, Decimal('0'), f"Payroll — {entry.employee.employee_number}"),
    ]
    if uif_employer > 0:
        lines.append(('OPEX_PAYE_UIF_EMPLOYER', uif_employer, Decimal('0'), f"Employer UIF — {entry.employee.employee_number}"))
    statutory_payable = paye + uif_employee + uif_employer
    if statutory_payable > 0:
        lines.append(('PAYE_UIF_PAYABLE', Decimal('0'), statutory_payable, f"PAYE/UIF — {entry.employee.employee_number}"))
    lines.append(('BANK_CASH', Decimal('0'), net_pay, f"Net pay — {entry.employee.employee_number}"))

    return post_transaction(
        'PayrollEntry', entry.id,
        entry.compliance_period.period_end if entry.compliance_period else entry.calculated_at.date(),
        f"Payroll — {entry.employee.first_name} {entry.employee.last_name}",
        lines, cash_flow_stream='ocf',
    )


def post_direct_sale_cash(cash_txn, revenue_system_key='REV_RETAIL'):
    """A cash/card/EFT sale with no Invoice behind it (POS retail, voucher sale)."""
    amount = Decimal(cash_txn.amount or 0)
    if amount <= 0:
        return None
    return post_transaction(
        'CashTransaction', cash_txn.id, cash_txn.created_at.date(),
        cash_txn.description or 'Direct sale',
        [
            ('BANK_CASH', amount, Decimal('0'), cash_txn.description),
            (revenue_system_key, Decimal('0'), amount, cash_txn.description),
        ],
        cash_flow_stream=cash_txn.cash_flow_stream, user=cash_txn.performed_by,
    )


def post_owner_capital_transaction(cash_txn):
    amount = Decimal(cash_txn.amount or 0)
    if amount <= 0:
        return None
    if cash_txn.transaction_category == 'capital_injection':
        lines = [
            ('BANK_CASH', amount, Decimal('0'), cash_txn.description),
            ('OWNERS_EQUITY', Decimal('0'), amount, cash_txn.description),
        ]
    else:  # owner_drawing
        lines = [
            ('OWNERS_DRAWINGS', amount, Decimal('0'), cash_txn.description),
            ('BANK_CASH', Decimal('0'), amount, cash_txn.description),
        ]
    return post_transaction(
        'CashTransaction', cash_txn.id, cash_txn.created_at.date(),
        cash_txn.description or cash_txn.transaction_category,
        lines, cash_flow_stream='fcf', user=cash_txn.performed_by,
    )

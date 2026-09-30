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
    ('1300', 'STAFF_LOANS', 'Staff Loans & Advances', 'asset', 'current_asset', 'debit'),
    ('1510', 'VAT_INPUT', 'VAT Input (Claimable)', 'asset', 'current_asset', 'debit'),

    ('2000', 'ACCOUNTS_PAYABLE', 'Accounts Payable (Creditors)', 'liability', 'current_liability', 'credit'),
    ('2100', 'VAT_PAYABLE', 'VAT Payable (Output)', 'liability', 'current_liability', 'credit'),
    ('2200', 'PAYE_UIF_PAYABLE', 'PAYE & UIF Payable', 'liability', 'current_liability', 'credit'),

    ('3000', 'OWNERS_EQUITY', "Owner's Equity / Capital", 'equity', '', 'credit'),
    ('3100', 'RETAINED_EARNINGS', 'Retained Earnings', 'equity', '', 'credit'),
    ('3200', 'OWNERS_DRAWINGS', "Owner's Drawings", 'equity', '', 'debit'),

    ('4000', 'REV_WIFI', 'WiFi Subscription Revenue', 'revenue', '', 'credit'),
    ('4100', 'REV_SLA', 'SLA Retainer Revenue', 'revenue', '', 'credit'),
    ('4150', 'REV_SERVICES', 'Email, Hosting & Other Services Revenue', 'revenue', '', 'credit'),
    ('4200', 'REV_ADHOC', 'Ad-Hoc / Project Revenue', 'revenue', '', 'credit'),
    ('4300', 'REV_RETAIL', 'Retail / POS Sales Revenue', 'revenue', '', 'credit'),

    ('5000', 'COGS_HARDWARE', 'Cost of Goods Sold — Hardware/Parts', 'expense', 'cogs', 'debit'),
    ('5100', 'COGS_AXXESS', 'Cost of Goods Sold — Axxess Wholesale', 'expense', 'cogs', 'debit'),
    ('5200', 'COGS_SERVICES', 'Cost of Services — Hosting / Email / Other', 'expense', 'cogs', 'debit'),

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


# name, kind, account system_key, cash-flow stream, description
SEED_EXPENSE_CATEGORIES = [
    ('Hardware & Parts Purchases', 'cogs', 'COGS_HARDWARE', 'ocf', 'Parts, devices and consumables bought for resale or repairs'),
    ('Rent', 'operating', 'OPEX_RENT', 'ocf', 'Office / workshop rent'),
    ('Utilities & Internet', 'operating', 'OPEX_UTILITIES', 'ocf', 'Electricity, water, data, airtime'),
    ('Bank Fees', 'operating', 'OPEX_BANKFEES', 'ocf', 'Account, card-machine and transaction fees'),
    ('Marketing & Advertising', 'operating', 'OPEX_MARKETING', 'ocf', 'Ads, flyers, sponsorships'),
    ('Fuel & Travel', 'operating', 'OPEX_OTHER', 'ocf', 'Fuel, tolls, call-out travel'),
    ('Software & Subscriptions', 'operating', 'OPEX_OTHER', 'ocf', 'Licences, hosting, SaaS'),
    ('Domains, Email & Hosting (own use)', 'operating', 'OPEX_OTHER', 'ocf', 'Rehumile\'s own domains, mailboxes and web hosting (not services resold to clients)'),
    ('Internet & Axxess (own lines)', 'operating', 'OPEX_UTILITIES', 'ocf', 'Axxess / internet lines used by Rehumile itself (client lines go on their subscription)'),
    ('Repairs & Maintenance', 'operating', 'OPEX_OTHER', 'ocf', 'Upkeep of premises and equipment'),
    ('Office & Sundry', 'operating', 'OPEX_OTHER', 'ocf', 'Stationery, cleaning, refreshments'),
    ('Equipment & Tools', 'capital', 'FIXED_ASSETS', 'icf', 'Long-life assets — not deducted from profit, shown as an asset'),
]


def seed_expense_categories():
    """Idempotent: creates the default categories once. Returns how many were created."""
    from .models import ExpenseCategory
    created = 0
    for order, (name, kind, key, stream, desc) in enumerate(SEED_EXPENSE_CATEGORIES):
        try:
            acct = Account.objects.get(system_key=key)
        except Account.DoesNotExist:
            continue
        _, was_created = ExpenseCategory.objects.get_or_create(
            name=name,
            defaults=dict(kind=kind, account=acct, default_cash_flow_stream=stream,
                          description=desc, is_system=True, display_order=order),
        )
        created += int(was_created)
    return created


def ensure_seeded():
    """Make sure the Chart of Accounts and default expense categories exist.
    Cheap when already seeded (two COUNT queries), so views can call it freely."""
    from .models import ExpenseCategory
    if Account.objects.count() < len(SEED_ACCOUNTS):
        seed_chart_of_accounts()
    if ExpenseCategory.objects.count() < len(SEED_EXPENSE_CATEGORIES):
        seed_expense_categories()


def account(system_key):
    try:
        return Account.objects.get(system_key=system_key)
    except Account.DoesNotExist:
        seed_chart_of_accounts()   # first posting on a fresh database
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
    ref = f"Invoice {invoice.invoice_number}"

    # Combined monthly-services invoices: revenue and cost are booked per line by service type.
    revenue = {}
    cost_wifi = cost_other = Decimal('0')
    items = list(invoice.items.all()) if invoice.invoice_type == 'subscription' else []
    if items:
        for it in items:
            key = {'wifi': 'REV_WIFI', 'sla': 'REV_SLA'}.get(it.service_type, 'REV_SERVICES')
            revenue[key] = revenue.get(key, Decimal('0')) + Decimal(it.amount or 0)
            line_cost = Decimal(it.quantity or 0) * Decimal(it.unit_cost or 0)
            if it.service_type == 'wifi':
                cost_wifi += line_cost
            else:
                cost_other += line_cost
        drift = subtotal - sum(revenue.values(), Decimal('0'))     # cents of rounding: keep the entry balanced
        if drift:
            first = next(iter(revenue))
            revenue[first] += drift
    else:
        revenue = {revenue_key: subtotal}
        if invoice.invoice_type == 'wifi':
            cost_wifi = Decimal(invoice.wholesale_cost or 0)

    lines = [('ACCOUNTS_RECEIVABLE', total, Decimal('0'), ref)]
    lines += [(key, Decimal('0'), amount, ref) for key, amount in revenue.items() if amount]
    if tax_amount > 0:
        lines.append(('VAT_PAYABLE', Decimal('0'), tax_amount, ref))
    if cost_wifi > 0:
        lines.append(('COGS_AXXESS', cost_wifi, Decimal('0'), f"Axxess cost — {invoice.invoice_number}"))
        lines.append(('ACCOUNTS_PAYABLE', Decimal('0'), cost_wifi, f"Axxess cost — {invoice.invoice_number}"))
    if cost_other > 0:
        lines.append(('COGS_SERVICES', cost_other, Decimal('0'), f"Service cost — {invoice.invoice_number}"))
        lines.append(('ACCOUNTS_PAYABLE', Decimal('0'), cost_other, f"Service cost — {invoice.invoice_number}"))

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


def post_expense_payment(expense, pay_date=None, user=None):
    """An unpaid (payable) expense has now been paid: Dr Accounts Payable, Cr Bank."""
    amount = Decimal(expense.amount or 0)
    if amount <= 0:
        return None
    from datetime import date as _date
    return post_transaction(
        'ExpensePayment', expense.id, pay_date or _date.today(),
        f"Paid supplier — {expense.vendor}",
        [
            ('ACCOUNTS_PAYABLE', amount, Decimal('0'), expense.vendor),
            ('BANK_CASH', Decimal('0'), amount, expense.vendor),
        ],
        cash_flow_stream=expense.cash_flow_stream, user=user,
    )


@db_transaction.atomic
def reverse_source(source_model, source_id, user=None):
    """
    Undo every posting made for a source record by posting mirror-image
    entries (the ledger is append-only — nothing is ever edited or deleted).
    Idempotent: a posting that is already reversed is skipped.
    """
    from datetime import date as _date
    reversed_count = 0
    originals = LedgerTransaction.objects.filter(
        source_model__in=[source_model, f"{source_model}Payment"], source_id=str(source_id), reverses__isnull=True,
    )
    for txn in originals:
        if txn.reversed_by.exists():
            continue
        rev = LedgerTransaction.objects.create(
            transaction_date=_date.today(), description=f"REVERSAL: {txn.description}",
            source_model=f"{txn.source_model}:reversal", source_id=str(source_id),
            cash_flow_stream=txn.cash_flow_stream, reverses=txn,
            created_by=user if user and getattr(user, 'is_authenticated', False) else None,
        )
        LedgerEntry.objects.bulk_create([
            LedgerEntry(transaction=rev, account=e.account, debit=e.credit, credit=e.debit, memo=f"Reversal — {e.memo}")
            for e in txn.entries.all()
        ])
        reversed_count += 1
    return reversed_count


def post_payroll_entry(entry):
    """
    Dr Salaries (gross)             Cr PAYE/UIF/SDL payable (SARS)
    Dr Employer levies (UIF + SDL)  Cr Staff loans (deductions recovered)
                                    Cr Bank (net pay)
    Always balances: net = gross - paye - uif_employee - other_deductions.
    """
    gross = Decimal(entry.total_gross or entry.gross_salary or 0)
    paye = Decimal(entry.paye_amount or 0)
    uif_employee = Decimal(entry.uif_employee or 0)
    uif_employer = Decimal(entry.uif_employer or 0)
    sdl = Decimal(entry.sdl_employer or 0)
    other_deductions = Decimal(entry.other_deductions or 0)
    net_pay = Decimal(entry.net_pay or 0)
    if gross <= 0:
        return None

    ref = entry.employee.employee_number
    lines = [('OPEX_SALARIES', gross, Decimal('0'), f"Payroll — {ref}")]
    if uif_employer + sdl > 0:
        lines.append(('OPEX_PAYE_UIF_EMPLOYER', uif_employer + sdl, Decimal('0'), f"Employer UIF/SDL — {ref}"))
    statutory_payable = paye + uif_employee + uif_employer + sdl
    if statutory_payable > 0:
        lines.append(('PAYE_UIF_PAYABLE', Decimal('0'), statutory_payable, f"PAYE/UIF/SDL — {ref}"))
    if other_deductions > 0:
        lines.append(('STAFF_LOANS', Decimal('0'), other_deductions, f"Deduction recovered — {ref}"))
    lines.append(('BANK_CASH', Decimal('0'), net_pay, f"Net pay — {ref}"))

    return post_transaction(
        'PayrollEntry', entry.id,
        entry.compliance_period.period_end if entry.compliance_period else entry.calculated_at.date(),
        f"Payroll — {entry.employee.first_name} {entry.employee.last_name}",
        lines, cash_flow_stream='ocf',
    )


def post_direct_sale_cash(cash_txn, revenue_system_key='REV_RETAIL'):
    """A cash/card/EFT sale with no Invoice behind it (POS retail)."""
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

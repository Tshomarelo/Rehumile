"""
Profit & Loss, explained line by line.

Two views of the same period (all amounts exclude VAT):
  accrual  revenue = invoices issued in the period; cost of sales = the full Axxess / supplier / job cost of those invoices
           (paid or not); running costs by expense date; payroll by pay month. "What the period earned."
  cash     money actually received in the period, and money actually paid out (supplier bills, parts and running costs
           marked paid in the period). "What moved in the bank."

Every figure carries the records behind it. Figures come from ims/finance.py (the same engine as the dashboard).
Internal only: it shows costs and margins, so it is never exposed to clients.
"""
from collections import OrderedDict
from datetime import date
from decimal import Decimal

from . import billing, costlines, finance
from .models import Expense, Invoice
from .timeutils import local_date

ZERO = Decimal('0')
VIEWS = ('accrual', 'cash')
STREAM_LABELS = {'wifi': 'WiFi / Internet', 'sla': 'SLA retainers', 'services': 'Email, hosting & other services', 'adhoc': 'Ad-hoc jobs & projects'}
ROW_LIMIT = 500


def _f(v):
    return finance._f(v)


def _money(v):
    return costlines.money(v)


def _group(label, rows, key=None):
    return {'key': key or label, 'label': label, 'amount': _f(sum((Decimal(str(r['amount'])) for r in rows), ZERO)), 'rows': rows[:ROW_LIMIT]}


def _invoice_line_rows(inv, frac, when, paid, with_cost=False):
    """Per-line rows of an invoice scaled by `frac`: revenue rows and (optionally) cost rows."""
    rev, cost = [], []
    lines = costlines.lines(inv)
    for ln in lines:
        base = {'ref': inv.invoice_number, 'label': finance._client_name(inv), 'line': ln['description'], 'branch': ln['site_name'],
                'date': when.isoformat() if when else None, 'paid': paid, 'url': costlines.invoice_link(inv)}
        a, c = ln['amount'] * frac, ln['cost'] * frac
        rev.append(dict(base, amount=_f(a), cost=_f(c), stream=ln['stream'], source=f"{ln['quantity']:g} × {_money(ln['unit_price'])}"))
        if c:
            cost.append(dict(base, amount=_f(c), revenue=_f(a), stream=ln['stream'], source=costlines.line_source(inv, ln, c)))
    # keep the rows adding up to the invoice's own figure (rounding, or lines not matching the subtotal)
    drift = inv.subtotal * frac - sum((Decimal(str(r['amount'])) for r in rev), ZERO)
    if abs(drift) >= Decimal('0.005'):
        rev.append({'ref': inv.invoice_number, 'label': finance._client_name(inv), 'line': 'Other / rounding', 'branch': '', 'date': when.isoformat() if when else None,
                    'paid': paid, 'url': costlines.invoice_link(inv), 'amount': _f(drift), 'cost': 0, 'stream': rev[0]['stream'] if rev else 'adhoc', 'source': ''})
    split = finance.invoice_split(inv)
    cdrift = (split['axxess'] + split['services_cost']) * frac - sum((Decimal(str(r['amount'])) for r in cost), ZERO)
    if abs(cdrift) >= Decimal('0.005'):
        cost.append({'ref': inv.invoice_number, 'label': finance._client_name(inv), 'line': 'Other recorded cost', 'branch': '', 'date': when.isoformat() if when else None,
                     'paid': paid, 'url': costlines.invoice_link(inv), 'amount': _f(cdrift), 'revenue': 0, 'stream': 'adhoc', 'source': 'Other recorded cost on the invoice'})
    return rev, cost


def _expense_row(e, paid_date=None):
    return {'ref': e.expense_category.name if e.expense_category_id else e.account.name, 'label': e.vendor, 'line': e.description,
            'date': (paid_date or e.expense_date).isoformat(), 'amount': _f(e.amount), 'paid': e.payment_status == 'paid',
            'source': ((f"Recurring cost “{e.recurring_source.name}”" if e.recurring_source_id else 'One-off expense') +
                       (f" — booked {e.expense_date:%d %b}, " + (f"paid {e.paid_on:%d %b %Y}" if e.paid_on else 'paid') if paid_date else
                        (' — paid' if e.payment_status == 'paid' else ' — UNPAID'))),
            'url': '/portal/dashboard/expenses/'}


def _own_line_total(bill):
    return sum((l.amount for l in bill.lines.all() if l.recurring_expense_id), ZERO)


def build(view='accrual', period='month', anchor=None, date_from=None, date_to=None, today=None):
    if view not in VIEWS:
        raise ValueError("view must be 'accrual' or 'cash'.")
    today = today or billing._today()
    start, end, label = finance.resolve_period(period, anchor, date_from, date_to, today=today)

    rev_rows, cost_rows = [], []
    if view == 'accrual':
        for inv in finance._issued(start, end):
            r, c = _invoice_line_rows(inv, Decimal('1'), local_date(inv.sent_at) if inv.sent_at else None, inv.status == 'paid')
            rev_rows += r
            cost_rows += c
    else:
        for ev in finance._paid_events(start, end):
            r, c = _invoice_line_rows(ev._inv, ev.frac, ev.payment_date, True)
            rev_rows += r
            cost_rows += c       # costs of invoices are only a cash outflow when paid to the supplier (bills below)
        cost_rows = []
    direct = [{'ref': t.payment_method.upper(), 'label': t.description, 'line': 'Till sale', 'date': t.created_at.date().isoformat(), 'amount': _f(t.amount),
               'paid': True, 'stream': 'direct', 'source': 'Sale taken at the till, no invoice', 'url': '/portal/dashboard/cash-management/'}
              for t in finance._direct_sales_qs(start, end)]
    rev_rows += direct

    # ── expenses ──
    base_exp = Expense.objects.select_related('expense_category', 'account', 'recurring_source', 'supplier_account').prefetch_related('lines')
    parts, opex_groups = [], OrderedDict()
    if view == 'accrual':
        for e in base_exp.filter(expense_date__gte=start, expense_date__lte=end, is_supplier_bill=False).order_by('expense_date'):
            if e.category == 'cogs':
                parts.append(_expense_row(e))
            elif e.category != 'capital':
                opex_groups.setdefault(e.expense_category.name if e.expense_category_id else e.account.name, []).append(_expense_row(e))
    else:
        paid_in = lambda e: e.paid_on or e.expense_date
        for e in base_exp.filter(payment_status='paid').order_by('expense_date'):
            d = paid_in(e)
            if not (start <= d <= end):
                continue
            if e.is_supplier_bill:
                own = _own_line_total(e)
                net = e.amount - own
                if net > 0:
                    row = _expense_row(e, d)
                    row.update(amount=_f(net), source=f"Supplier bill paid — {e.supplier_account or e.vendor}" + (f" (our own lines {_money(own)} are counted as running costs)" if own else ''))
                    cost_rows.append(row)
            elif e.category == 'cogs':
                parts.append(_expense_row(e, d))
            elif e.category != 'capital':
                opex_groups.setdefault(e.expense_category.name if e.expense_category_id else e.account.name, []).append(_expense_row(e, d))
    cost_groups = []
    if view == 'accrual':
        by_stream = OrderedDict()
        for r in cost_rows:
            by_stream.setdefault(r['stream'], []).append(r)
        for k, rows in by_stream.items():
            cost_groups.append(_group(f"Axxess / supplier cost — {STREAM_LABELS.get(k, k)}", rows, k))
    elif cost_rows:
        cost_groups.append(_group('Supplier bills paid (e.g. Axxess account)', cost_rows, 'supplier_bills'))
    if parts:
        cost_groups.append(_group('Parts / stock bought', parts, 'parts'))
    opex = [_group(k, v, k) for k, v in opex_groups.items()]

    payroll_rows = [{'ref': p.employee.employee_number, 'label': f"{p.employee.first_name} {p.employee.last_name}", 'line': 'Approved payslip',
                     'date': p.compliance_period.period_end.isoformat(), 'amount': _f(p.employer_cost), 'paid': True,
                     'source': f"Salary plus employer UIF/SDL, pay month ending {p.compliance_period.period_end:%d %b %Y}", 'url': '/portal/dashboard/hr/#payroll'}
                    for p in finance._payroll_qs(start, end).select_related('employee', 'compliance_period')]

    # ── totals ──
    D = lambda x: Decimal(str(x))
    revenue_total = sum((D(r['amount']) for r in rev_rows), ZERO)
    cos_total = sum((D(g['amount']) for g in cost_groups), ZERO)
    opex_total = sum((D(g['amount']) for g in opex), ZERO)
    payroll_total = sum((D(r['amount']) for r in payroll_rows), ZERO)
    gross = revenue_total - cos_total
    net = gross - opex_total - payroll_total

    # revenue by service type and by client
    by_stream, by_client = OrderedDict(), OrderedDict()
    for r in rev_rows:
        by_stream.setdefault(r['stream'], []).append(r)
        by_client.setdefault(r['label'], []).append(r)
    revenue_groups = [_group(STREAM_LABELS.get(k, 'Till / POS sales' if k == 'direct' else k), v, k) for k, v in by_stream.items()]
    clients = sorted(({'client': k, 'amount': _f(sum((D(r['amount']) for r in v), ZERO)), 'cost': _f(sum((D(r.get('cost', 0)) for r in v), ZERO)),
                       'rows': v[:ROW_LIMIT]} for k, v in by_client.items()), key=lambda x: -x['amount'])

    accrual_note = ("Revenue is every invoice issued in the period (excl. VAT), whether or not the client has paid. The Axxess / supplier / job cost of those same "
                    "invoices is counted in full as cost of sales, so profit is not flattered by unpaid invoices.")
    cash_note = ("Revenue is money actually received in the period (excl. VAT). Cost of sales is what we actually paid out: supplier bills (e.g. the Axxess account) and "
                 "parts marked paid in the period. If you have not logged the Axxess bill, there is no supplier cost here yet.")
    sections = {
        'revenue': {'label': 'Revenue', 'amount': _f(revenue_total), 'groups': revenue_groups, 'by_client': clients,
                    'explain': accrual_note.split('. ')[0] + '.' if view == 'accrual' else 'Money actually received in the period (excl. VAT), plus till sales.'},
        'cost_of_sales': {'label': 'Cost of sales', 'amount': _f(cos_total), 'groups': cost_groups,
                          'explain': ('The full Axxess / supplier / job cost on each invoice line issued in the period, plus parts bought. Taken line by line from the invoices.' if view == 'accrual'
                                      else 'Supplier bills and parts actually paid in the period.')},
        'operating': {'label': 'Operating expenses', 'amount': _f(opex_total), 'groups': opex,
                      'explain': ('Running costs by expense date, grouped by category (recurring costs included; equipment bought is an asset and left out).' if view == 'accrual'
                                  else 'Running costs that were marked paid in the period, by category.')},
        'payroll': {'label': 'Payroll', 'amount': _f(payroll_total), 'rows': payroll_rows,
                    'explain': 'Approved payslips (salary plus employer UIF/SDL) for pay months ending in the period.' if payroll_rows else 'R0 — no approved payroll for this period.'},
    }
    lines = [
        {'key': 'revenue', 'label': 'Revenue', 'sign': '+', 'amount': _f(revenue_total)},
        {'key': 'cost_of_sales', 'label': 'Cost of sales', 'sign': '−', 'amount': _f(cos_total)},
        {'key': 'gross', 'label': 'Gross profit', 'sign': '=', 'amount': _f(gross), 'total': True},
        {'key': 'operating', 'label': 'Operating expenses', 'sign': '−', 'amount': _f(opex_total)},
        {'key': 'payroll', 'label': 'Payroll', 'sign': '−', 'amount': _f(payroll_total)},
        {'key': 'net', 'label': 'Net profit', 'sign': '=', 'amount': _f(net), 'total': True},
    ]

    # ── what is owed to us / what we owe (as at today) ──
    owed_rows = []
    for inv in finance._unpaid_qs(today).select_related('company', 'wifi_subscriber', 'sla_contract').order_by('due_date'):
        late = (today - inv.due_date).days if inv.due_date and inv.due_date < today else 0
        owed_rows.append({'ref': inv.invoice_number, 'label': finance._client_name(inv), 'issued': local_date(inv.sent_at).isoformat() if inv.sent_at else None,
                          'due': inv.due_date.isoformat() if inv.due_date else None, 'days_overdue': late, 'total': _f(inv.total_amount),
                          'paid': _f(inv.amount_paid), 'amount': _f(inv.balance_due), 'overdue': late > 0, 'url': costlines.invoice_link(inv)})
    owe_rows = []
    for e in base_exp.filter(payment_status='unpaid').order_by('expense_date'):
        owe_rows.append({'ref': str(e.supplier_account) if e.supplier_account_id else (e.expense_category.name if e.expense_category_id else e.account.name),
                         'label': e.vendor, 'line': e.description, 'date': e.expense_date.isoformat(), 'amount': _f(e.amount), 'supplier_bill': e.is_supplier_bill,
                         'url': '/portal/dashboard/expenses/?unpaid=1'})
    owed_total = sum((D(r['amount']) for r in owed_rows), ZERO)
    overdue_total = sum((D(r['amount']) for r in owed_rows if r['overdue']), ZERO)
    owe_total = sum((D(r['amount']) for r in owe_rows), ZERO)
    by_vendor = OrderedDict()
    for r in owe_rows:
        by_vendor[r['label']] = by_vendor.get(r['label'], ZERO) + D(r['amount'])

    warnings = []
    if view == 'cash' and not any(g['key'] == 'supplier_bills' for g in cost_groups):
        warnings.append({'title': 'No supplier bills paid in this period', 'detail': 'Log the Axxess account bill under Expenses > Supplier bills and mark it paid, otherwise the cash view shows no Axxess cost.',
                         'url': '/portal/dashboard/expenses/'})
    no_cost = sorted({r['ref'] for r in rev_rows if r.get('stream') in ('wifi', 'services', 'adhoc') and r.get('cost', 0) == 0 and r['amount'] and r.get('ref', '').startswith('INV')})
    if view == 'accrual' and no_cost:
        warnings.append({'title': f"{len(no_cost)} invoice line(s) have no cost recorded", 'detail': 'They count as 100% profit: ' + ', '.join(no_cost[:15]) + ('…' if len(no_cost) > 15 else ''),
                         'url': '/portal/invoices/'})

    return {
        'view': view, 'view_label': 'Accrual — what the period earned' if view == 'accrual' else 'Cash — money in and out',
        'period': {'start': start.isoformat(), 'end': end.isoformat(), 'label': label, 'kind': period}, 'as_of': today.isoformat(), 'generated_at': None,
        'note': accrual_note if view == 'accrual' else cash_note,
        'lines': lines, 'margin_pct': round(float(net / revenue_total * 100), 1) if revenue_total else 0, 'sections': sections,
        'owed_to_us': {'amount': _f(owed_total), 'overdue': _f(overdue_total), 'not_due': _f(owed_total - overdue_total), 'rows': owed_rows,
                       'explain': 'Invoices issued and not fully paid, as at today (balances include VAT because that is what clients will pay).'},
        'we_owe': {'amount': _f(owe_total), 'rows': owe_rows, 'by_vendor': [{'vendor': k, 'amount': _f(v)} for k, v in by_vendor.items()],
                   'explain': 'Expenses and supplier bills (e.g. the Axxess account) that are marked unpaid, so we still have to pay them.'},
        'warnings': warnings,
    }

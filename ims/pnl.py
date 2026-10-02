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
import re
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

    rev_rows, cost_rows, job_rows = [], [], []
    jobmap = finance.job_costs_by_invoice()
    linked_ids = {e.id for lst in jobmap.values() for e in lst}
    if view == 'accrual':
        for inv in finance._issued(start, end):
            r, c = _invoice_line_rows(inv, Decimal('1'), finance.invoice_period_date(inv), inv.status == 'paid')
            rev_rows += r
            cost_rows += c
            for e in jobmap.get(inv.id, []):         # job / parts / labour costs tied to this invoice count with it
                job_rows.append({'ref': inv.invoice_number, 'label': finance._client_name(inv), 'line': e.description or e.vendor, 'branch': '',
                                 'date': (finance.invoice_period_date(inv) or e.expense_date).isoformat(), 'paid': e.payment_status == 'paid', 'amount': _f(e.amount),
                                 'stream': 'job', 'source': f"Job cost logged as an expense — {e.vendor}, {e.expense_date:%d %b %Y}" + ('' if e.payment_status == 'paid' else ' (unpaid)'),
                                 'url': '/portal/dashboard/expenses/'})
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
            if e.id in linked_ids:
                continue
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
    if job_rows:
        cost_groups.append(_group('Job / parts / labour costs tied to invoices', job_rows, 'job_costs'))
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
    for inv in finance.open_issued_qs(today).select_related('company', 'wifi_subscriber', 'sla_contract').order_by('due_date'):
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
    linked = {i.invoice_number for i in Invoice.objects.filter(id__in=finance.job_cost_invoice_ids())}
    no_cost = sorted({r['ref'] for r in rev_rows if r['ref'] not in linked and r.get('stream') in ('wifi', 'services', 'adhoc') and r.get('cost', 0) == 0 and r['amount'] and r.get('ref', '').startswith('INV')})
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


# ─────────────────────────────────────────────────────────────────────────────
# Profit by invoice: one row per invoice for a month, so the owner can budget on real figures
# ─────────────────────────────────────────────────────────────────────────────

SERVICE_WORDS = {'wifi': 'Axxess', 'email': 'email', 'hosting': 'hosting', 'domain': 'domain', 'sla': 'SLA'}


def _short(text, n=40):
    text = ' '.join((text or '').split())
    return text if len(text) <= n else text[:n - 1].rstrip() + '…'


def _expense_label(e):
    text = re.sub(r'\(?\s*invoice\s+INV-[\w-]+\s*\)?', '', e.description or '', flags=re.I).strip(' -—:')
    return _short(text or (e.expense_category.name if e.expense_category_id else e.vendor), 30)


def _cost_note(inv, lines, jobs, cost, engine_line_cost):
    """'Axxess R700 + hosting R300' / 'supplies R1,250 + labour R600' / 'no cost recorded'."""
    if cost == 0:
        return 'no cost recorded'
    parts = OrderedDict()
    for ln in lines:
        if ln['cost']:
            word = SERVICE_WORDS.get(ln['service_type']) or _short(ln['description'], 24)
            parts[word] = parts.get(word, ZERO) + ln['cost']
    drift = engine_line_cost - sum(parts.values(), ZERO)
    if abs(drift) >= Decimal('0.005'):
        parts['other cost'] = parts.get('other cost', ZERO) + drift
    for e in jobs:
        parts[_expense_label(e)] = parts.get(_expense_label(e), ZERO) + e.amount
    return ' + '.join(f"{k} {_money(v)}" for k, v in parts.items() if v)


def profit_by_invoice(month=None, today=None):
    today = today or billing._today()
    if month:
        y, m = (int(x) for x in str(month)[:7].split('-'))
    else:
        y, m = today.year, today.month
    start, end = billing.month_bounds(y, m)
    jobmap = finance.job_costs_by_invoice()
    linked_ids = {e.id for lst in jobmap.values() for e in lst}
    invoices = finance._issued(start, end)

    unpaid, paid = [], []
    for inv in sorted(invoices, key=lambda i: (finance._client_name(i).lower(), i.invoice_number)):
        lines = costlines.lines(inv)
        split = finance.invoice_split(inv)
        engine_line_cost = split['axxess'] + split['services_cost']
        jobs = jobmap.get(inv.id, [])
        cost = engine_line_cost + sum((e.amount for e in jobs), ZERO)       # the same cost the accrual P&L and the dashboard use
        amount = inv.subtotal
        job_text = inv.description or '; '.join(ln['description'] for ln in lines)
        note = _cost_note(inv, lines, jobs, cost, engine_line_cost)
        if inv.status == 'partially_paid':
            note += f" · part-paid, {_money(inv.amount_paid)} received"
        row = {'id': str(inv.id), 'invoice': inv.invoice_number, 'client': finance._client_name(inv), 'job': _short(job_text), 'amount': _f(amount),
               'cost': _f(cost), 'profit': _f(amount - cost), 'note': note, 'status': inv.status, 'no_cost': cost == 0,
               'url': costlines.invoice_link(inv), 'period': (finance.invoice_period_date(inv) or start).isoformat()}
        (paid if inv.status == 'paid' else unpaid).append(row)

    def totals(rows):
        a, c = sum((D(r['amount']) for r in rows), ZERO), sum((D(r['cost']) for r in rows), ZERO)
        return {'amount': _f(a), 'cost': _f(c), 'profit': _f(a - c)}

    D = lambda x: Decimal(str(x))
    tu, tp = totals(unpaid), totals(paid)

    # running costs: everything that is not tied to an invoice and is not a supplier account bill
    exp = Expense.objects.select_related('expense_category', 'account').filter(expense_date__gte=start, expense_date__lte=end, is_supplier_bill=False).order_by('expense_date')
    groups = OrderedDict()
    for e in exp:
        if e.id in linked_ids or e.category == 'capital':
            continue
        name = ('Parts / stock bought' if e.category == 'cogs' else (e.expense_category.name if e.expense_category_id else e.account.name))
        groups.setdefault(name, []).append({'label': e.vendor, 'line': e.description, 'date': e.expense_date.isoformat(), 'amount': _f(e.amount),
                                            'paid': e.payment_status == 'paid', 'url': '/portal/dashboard/expenses/'})
    running = [{'item': k, 'amount': _f(sum((D(r['amount']) for r in v), ZERO)), 'rows': v} for k, v in groups.items()]
    running_total = sum((D(g['amount']) for g in running), ZERO)

    payroll_total = sum((p.employer_cost for p in finance._payroll_qs(start, end)), ZERO)
    till = sum((t.amount for t in finance._direct_sales_qs(start, end)), ZERO)
    invoiced = D(tu['amount']) + D(tp['amount'])
    costs = D(tu['cost']) + D(tp['cost'])
    gross = invoiced + till - costs
    net = gross - running_total - payroll_total
    summary_lines = [{'key': 'invoiced', 'label': 'Invoiced in the period (still unpaid + already paid)', 'sign': '+', 'amount': _f(invoiced)}]
    if till:
        summary_lines.append({'key': 'till', 'label': 'Till sales', 'sign': '+', 'amount': _f(till)})
    summary_lines += [{'key': 'costs', 'label': 'Less costs on invoices', 'sign': '−', 'amount': _f(costs)},
                      {'key': 'gross', 'label': 'Gross profit', 'sign': '=', 'amount': _f(gross), 'total': True},
                      {'key': 'running', 'label': 'Less running costs', 'sign': '−', 'amount': _f(running_total)}]
    if payroll_total:
        summary_lines.append({'key': 'payroll', 'label': 'Less payroll', 'sign': '−', 'amount': _f(payroll_total)})
    summary_lines.append({'key': 'net', 'label': 'NET PROFIT', 'sign': '=', 'amount': _f(net), 'total': True})

    # supplier account bills for the month: already counted above through the invoices / recurring costs
    bills = []
    for b in Expense.objects.select_related('supplier_account').prefetch_related('lines').filter(is_supplier_bill=True, expense_date__gte=start, expense_date__lte=end).order_by('supplier_account__account_number'):
        covers = ', '.join(l.description for l in b.lines.all()) or b.description or b.vendor
        bills.append({'id': str(b.id), 'account': b.supplier_account.account_number if b.supplier_account_id else b.vendor, 'covers': _short(covers, 80),
                      'status': b.payment_status, 'amount': _f(b.amount), 'paid_on': b.paid_on.isoformat() if b.paid_on else None})
    bills_total = sum((D(b['amount']) for b in bills), ZERO)
    still_to_pay = sum((D(b['amount']) for b in bills if b['status'] != 'paid'), ZERO)

    # the check: this report, the dashboard figure and the accrual P&L must agree to the rand
    dash_net = D(finance.accrual_summary(start, end, today)['profit_if_paid'])
    pnl_net = D(next(l['amount'] for l in build('accrual', 'month', start, today=today)['lines'] if l['key'] == 'net'))
    ok = abs(net - dash_net) < Decimal('0.005') and abs(net - pnl_net) < Decimal('0.005')
    # job costs dated this month that belong to an invoice outside this month's list (draft / another month): not counted here
    in_list = {i.id for i in invoices}
    stray = [e for inv_id, lst in jobmap.items() if inv_id not in in_list for e in lst if start <= e.expense_date <= end]
    warnings = []
    if not ok:
        warnings.append({'kind': 'mismatch', 'title': 'This report does not agree with the dashboard / Profit & Loss',
                         'detail': f"Report net profit {_money(net)}, dashboard {_money(dash_net)}, Profit & Loss {_money(pnl_net)}. Please tell support."})
    if stray:
        warnings.append({'kind': 'stray_job_costs', 'title': f"{len(stray)} job cost(s) worth {_money(sum((e.amount for e in stray), ZERO))} belong to invoices that are not in this month's list",
                         'detail': 'They count with their invoice (a draft or another month), not here: ' + '; '.join(_short(e.description or e.vendor, 40) for e in stray[:5])})
    no_cost = [r['invoice'] for r in unpaid + paid if r['no_cost']]
    if no_cost:
        warnings.append({'kind': 'no_cost', 'title': f"{len(no_cost)} invoice(s) have no cost recorded (shown as 100% profit)", 'detail': ', '.join(no_cost[:20])})
    return {
        'month': start.strftime('%Y-%m'), 'label': start.strftime('%B %Y'), 'period': {'start': start.isoformat(), 'end': end.isoformat(), 'label': start.strftime('%B %Y')},
        'unpaid': {'rows': unpaid, 'totals': tu}, 'paid': {'rows': paid, 'totals': tp},
        'running': {'items': running, 'amount': _f(running_total)}, 'summary': summary_lines, 'net_profit': _f(net),
        'suppliers': {'rows': bills, 'total': _f(bills_total), 'still_to_pay': _f(still_to_pay),
                      'note': 'Already counted above (through the invoices and your own recurring costs) — not an extra cost.'},
        'check': {'report': _f(net), 'dashboard': _f(dash_net), 'pnl': _f(pnl_net), 'ok': ok}, 'warnings': warnings,
        'note': 'All amounts exclude VAT. Draft and cancelled invoices are left out. Invoices are placed in a month by their billing period.',
        'generated_at': None,
    }

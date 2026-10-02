"""
"Profit & Money Owed" report.

Every figure here is derived from ims/finance.py (the single source of truth the dashboard also uses), amounts
excluding VAT, so the report and the dashboard can never disagree. Each headline amount is the sum of the
drill-down rows beneath it, and every row points at the record it came from.

Basis:
  received  money that actually arrived in the period (by payment date) + till sales
  owed      invoices issued but not fully paid (what is still to come in)
  full      received + still owed

Costs are internal. This module is only used by admin/finance endpoints; nothing here is client-facing.
"""
from collections import OrderedDict
from datetime import date
from decimal import Decimal

from . import billing, finance
from .costlines import lines as _lines, line_source as _line_source, money as _money, invoice_link as _invoice_link
from .timeutils import local_date
from .models import Invoice, RecurringExpense

ZERO = Decimal('0')
BASES = ('received', 'owed', 'full')
BASIS_LABELS = {
    'received': 'Received (cash basis, by payment date)',
    'owed': 'Still owed (unpaid invoices only)',
    'full': 'Full picture (received + still owed)',
}
ROW_LIMIT = 500


def _f(v):
    return finance._f(v)


def _owed_frac(inv):
    total = inv.total_amount or ZERO
    return (inv.balance_due / total) if total else ZERO


def _days_overdue(inv, as_of):
    if inv.due_date and inv.due_date < as_of and inv.balance_due > 0:
        return (as_of - inv.due_date).days
    return 0


def build(period='month', anchor=None, date_from=None, date_to=None, basis='received', today=None):
    if basis not in BASES:
        raise ValueError(f"basis must be one of: {', '.join(BASES)}.")
    today = today or billing._today()
    start, end, label = finance.resolve_period(period, anchor, date_from, date_to, today=today)
    as_of = min(end, today)

    # ── 1. which invoices, and what share of each counts ───────────────────
    entries = OrderedDict()          # invoice id -> {'inv', 'recv', 'owed', 'paid_on': [dates]}

    def entry(inv):
        return entries.setdefault(inv.id, {'inv': inv, 'recv': ZERO, 'owed': ZERO, 'paid_on': []})

    direct = []
    if basis in ('received', 'full'):
        for ev in finance._paid_events(start, end):
            e = entry(ev._inv)
            e['recv'] += ev.frac
            e['paid_on'].append(ev.payment_date)
        direct = list(finance._direct_sales_qs(start, end).order_by('-created_at'))
    if basis in ('owed', 'full'):
        for inv in finance._unpaid_qs(as_of).select_related('company', 'wifi_subscriber', 'sla_contract').prefetch_related('items__subscription'):
            frac = _owed_frac(inv)
            if frac > 0:
                entry(inv)['owed'] += frac
    rows_inv = []
    prov_rows = []
    for e in sorted(entries.values(), key=lambda x: (x['inv'].due_date or date.max, x['inv'].invoice_number)):
        inv = e['inv']
        frac = e['recv'] + e['owed']
        full_split = finance.invoice_split(inv)
        counted = inv.subtotal * frac
        cost_total = (full_split['axxess'] + full_split['services_cost']) * frac
        lines = []
        line_cost_sum = ZERO
        for ln in _lines(inv):
            c_cost = ln['cost'] * frac
            line_cost_sum += c_cost
            lines.append({
                'description': ln['description'], 'branch': ln['site_name'], 'service_type': ln['service_type'],
                'quantity': float(ln['quantity']), 'unit_price': _f(ln['unit_price']), 'amount': _f(ln['amount']),
                'cost_per_unit': _f(ln['unit_cost']), 'cost': _f(ln['cost']), 'profit': _f(ln['profit']),
                'counted': _f(ln['amount'] * frac), 'counted_cost': _f(c_cost),
                'source': _line_source(inv, ln, ln['cost']) if ln['cost'] else '',
            })
            if c_cost:
                prov_rows.append({
                    'ref': inv.invoice_number, 'label': finance._client_name(inv), 'amount': _f(c_cost),
                    'source': _line_source(inv, ln, c_cost), 'url': _invoice_link(inv),
                })
        drift = cost_total - line_cost_sum
        if abs(drift) >= Decimal('0.005'):          # keep the proof adding up to the engine's figure
            prov_rows.append({'ref': inv.invoice_number, 'label': finance._client_name(inv), 'amount': _f(drift),
                              'source': 'Other recorded cost on the invoice', 'url': _invoice_link(inv)})
        rows_inv.append({
            'id': str(inv.id), 'number': inv.invoice_number, 'client': finance._client_name(inv), 'status': inv.status,
            'period_start': inv.billing_period_start.isoformat() if inv.billing_period_start else None,
            'period_end': inv.billing_period_end.isoformat() if inv.billing_period_end else None,
            'issued': local_date(inv.sent_at).isoformat() if inv.sent_at else None,
            'due': inv.due_date.isoformat() if inv.due_date else None, 'days_overdue': _days_overdue(inv, as_of),
            'total': _f(inv.total_amount), 'paid': _f(inv.amount_paid), 'balance': _f(inv.balance_due),
            'counted': _f(counted), 'counted_received': _f(inv.subtotal * e['recv']), 'counted_owed': _f(inv.subtotal * e['owed']),
            'cost': _f(cost_total), 'profit': _f(counted - cost_total),
            'no_cost': cost_total == 0 and counted > 0, 'lines': lines, 'url': _invoice_link(inv),
            '_inv': inv, '_frac': frac, '_cost': cost_total, '_counted': counted, '_owed_frac': e['owed'], '_paid_on': e['paid_on'],
        })

    direct_total = sum((t.amount for t in direct), ZERO)
    invoice_total = sum((r['_counted'] for r in rows_inv), ZERO)
    revenue_total = invoice_total + direct_total
    invoice_cost = sum((r['_cost'] for r in rows_inv), ZERO)

    # ── 2. costs from finance's own queries ────────────────────────────────
    expenses = list(finance._expense_qs(start, end).select_related('expense_category', 'account', 'recurring_source').order_by('expense_date'))
    cogs = [x for x in expenses if x.category == 'cogs']
    opex = [x for x in expenses if x.category not in ('cogs', 'capital')]
    for x in cogs:
        prov_rows.append({'ref': x.vendor, 'label': x.description or x.vendor, 'amount': _f(x.amount),
                          'source': f"Parts / stock bought {_money(x.amount)} — {x.vendor} ({x.expense_date:%d %b %Y})",
                          'url': '/portal/dashboard/expenses/'})
    provider_total = invoice_cost + sum((x.amount for x in cogs), ZERO)

    running_rows = []
    for x in opex:
        running_rows.append({
            'ref': x.expense_category.name if x.expense_category_id else x.account.name, 'label': x.vendor,
            'date': x.expense_date.isoformat(), 'amount': _f(x.amount),
            'source': (f"Recurring cost “{x.recurring_source.name}” — {x.vendor}" if x.recurring_source_id else f"One-off expense — {x.vendor}")
                      + (f": {x.description}" if x.description and not x.recurring_source_id else ''),
            'recurring': bool(x.recurring_source_id), 'paid': x.payment_status == 'paid', 'url': '/portal/dashboard/expenses/',
        })
    running_total = sum((x.amount for x in opex), ZERO)

    templates = []
    unposted = []
    posted_by_tpl = {}
    for x in expenses:
        if x.recurring_source_id:
            posted_by_tpl[x.recurring_source_id] = posted_by_tpl.get(x.recurring_source_id, ZERO) + x.amount
    for tpl in RecurringExpense.objects.select_related('expense_category').filter(is_active=True).order_by('name'):
        due_now = tpl.occurrences(today)
        posted = posted_by_tpl.get(tpl.id, ZERO)
        status = 'posted' if posted else ('due — not yet posted' if due_now else 'not due in this period')
        templates.append({'name': tpl.name, 'supplier': tpl.vendor, 'category': tpl.expense_category.name, 'amount': _f(tpl.amount),
                          'frequency': tpl.get_frequency_display(), 'posted_in_period': _f(posted), 'status': status,
                          'url': '/portal/dashboard/expenses/#recurring'})
        if due_now:
            unposted.append(tpl)

    payroll = list(finance._payroll_qs(start, end).select_related('employee', 'compliance_period'))
    payroll_total = sum((p.employer_cost for p in payroll), ZERO)
    payroll_rows = [{'ref': p.employee.employee_number, 'label': f"{p.employee.first_name} {p.employee.last_name}",
                     'date': p.compliance_period.period_end.isoformat(), 'amount': _f(p.employer_cost),
                     'source': f"Approved payslip — pay month ending {p.compliance_period.period_end:%d %b %Y}",
                     'url': '/portal/dashboard/hr/#payroll'} for p in payroll]

    net = revenue_total - provider_total - running_total - payroll_total

    # ── 3. headline ────────────────────────────────────────────────────────
    rev_label = {'received': 'Money received', 'owed': 'Unpaid invoices', 'full': 'Received + still owed'}[basis]
    net_label = 'Net profit' if basis == 'received' else 'Expected net profit'
    headline = [
        {'key': 'revenue', 'label': rev_label, 'sign': '+', 'amount': _f(revenue_total)},
        {'key': 'provider_costs', 'label': 'Service-provider costs', 'sign': '−', 'amount': _f(provider_total)},
        {'key': 'running_costs', 'label': 'Running costs', 'sign': '−', 'amount': _f(running_total)},
        {'key': 'payroll', 'label': 'Payroll', 'sign': '−', 'amount': _f(payroll_total)},
        {'key': 'net', 'label': net_label, 'sign': '=', 'amount': _f(net)},
    ]
    equation = ' − '.join(f"{h['label']} {_money(h['amount'])}" for h in headline[:4]) + f" = {net_label} {_money(net)}"

    n_inv = len(rows_inv)
    explain = {
        'revenue': {
            'received': f"{n_inv} invoice(s) paid between {start:%d %b} and {end:%d %b %Y}, plus {len(direct)} till sale(s). VAT is not our income, so it is left out.",
            'owed': f"{n_inv} invoice(s) issued up to {as_of:%d %b %Y} that clients have not fully paid yet. Only the balance still owed counts, without VAT.",
            'full': f"Money that arrived this period plus what is still owed on {n_inv} invoice(s). VAT is left out.",
        }[basis],
        'provider_costs': 'What the suppliers behind these invoices cost us (Axxess, hosting, email, parts and job costs), taken from the cost recorded on each invoice line.',
        'running_costs': 'Costs of keeping the business running this period: recurring costs (Axxess lines, domains, email) plus one-off expenses. Equipment bought is not counted as it is an asset.',
        'payroll': (f"Approved payslips (salary plus employer UIF/SDL) for pay months ending in this period."
                    if payroll else 'R0 — no approved payroll for this period yet; draft payroll is not counted until approved.'),
    }

    # ── 4. warnings ────────────────────────────────────────────────────────
    warnings = []
    no_cost = [r for r in rows_inv if r['no_cost']]
    if no_cost:
        warnings.append({
            'kind': 'no_cost', 'title': f"{len(no_cost)} invoice(s) have no cost recorded — they show as 100% profit",
            'detail': 'Add the supplier cost on the invoice line (or the service) so the profit is real.',
            'rows': [{'ref': r['number'], 'label': r['client'], 'amount': r['counted'], 'url': r['url']} for r in no_cost],
        })
    drafts = list(Invoice.objects.filter(status='draft').select_related('company').order_by('invoice_number'))
    if drafts:
        warnings.append({
            'kind': 'drafts', 'title': f"{len(drafts)} draft invoice(s) not issued — left out of the totals",
            'detail': 'Issue them (or delete them) so they are counted. Their cost may not be recorded yet.',
            'rows': [{'ref': d.invoice_number, 'label': finance._client_name(d), 'amount': _f(d.subtotal), 'url': _invoice_link(d)} for d in drafts],
        })
    late_paid = []
    for r in rows_inv:
        inv = r['_inv']
        for d in r['_paid_on']:
            if inv.billing_period_end and (d.year, d.month) > (inv.billing_period_end.year, inv.billing_period_end.month):
                late_paid.append({'ref': inv.invoice_number, 'label': r['client'], 'amount': r['counted_received'], 'url': r['url'],
                                  'note': f"{inv.billing_period_end:%B %Y} work paid on {d:%d %b %Y}"})
                break
    if late_paid:
        warnings.append({
            'kind': 'late_paid', 'title': f"{len(late_paid)} payment(s) dated in a later month than the work",
            'detail': 'The money counts in the month it arrived, not the month of the work. Check the payment date is right.',
            'rows': late_paid,
        })
    if unposted:
        warnings.append({
            'kind': 'recurring_unposted', 'title': f"{len(unposted)} recurring cost(s) due but not posted",
            'detail': 'They are posted automatically when finance pages load; if this stays, open the recurring costs tab and run them.',
            'rows': [{'ref': t.name, 'label': t.vendor, 'amount': _f(t.amount), 'url': '/portal/dashboard/expenses/#recurring'} for t in unposted],
        })
    cancelled = list(Invoice.objects.filter(status='cancelled').select_related('company', 'source_quotation').order_by('invoice_number')[:ROW_LIMIT])
    if cancelled:
        rows_c = []
        for c in cancelled:
            q = getattr(c, 'source_quotation', None)
            reason = f"replaced by quotation {q.quote_number}" if q else 'cancelled'
            rows_c.append({'ref': c.invoice_number, 'label': finance._client_name(c), 'amount': _f(c.subtotal), 'url': _invoice_link(c), 'note': reason})
        warnings.append({'kind': 'cancelled', 'title': f"{len(cancelled)} cancelled invoice(s) excluded",
                         'detail': 'Cancelled invoices never count as income or as money owed.', 'rows': rows_c})

    # ── 5. per client (branches under their head office) ───────────────────
    clients = OrderedDict()
    for r in rows_inv:
        inv, frac = r['_inv'], r['_frac']
        name = r['client']
        c = clients.setdefault(name, {'client': name, 'amount': ZERO, 'owed': ZERO, 'cost': ZERO, 'overdue': ZERO,
                                      'oldest_due': None, 'invoices': 0, 'branches': OrderedDict()})
        c['invoices'] += 1
        c['amount'] += r['_counted']
        c['owed'] += inv.subtotal * r['_owed_frac']
        c['cost'] += r['_cost']
        if r['days_overdue']:
            c['overdue'] += inv.subtotal * r['_owed_frac']
        if inv.due_date and r['_owed_frac'] > 0 and (c['oldest_due'] is None or inv.due_date < c['oldest_due']):
            c['oldest_due'] = inv.due_date
        for ln in r['lines']:
            b = c['branches'].setdefault(ln['branch'] or 'Head office', {'branch': ln['branch'] or 'Head office', 'amount': ZERO, 'cost': ZERO})
            b['amount'] += Decimal(str(ln['counted']))
            b['cost'] += Decimal(str(ln['counted_cost']))
    client_rows = []
    for c in sorted(clients.values(), key=lambda x: -x['amount']):
        client_rows.append({
            'client': c['client'], 'invoices': c['invoices'], 'amount': _f(c['amount']), 'owed': _f(c['owed']), 'cost': _f(c['cost']),
            'profit': _f(c['amount'] - c['cost']), 'overdue': _f(c['overdue']),
            'oldest_due': c['oldest_due'].isoformat() if c['oldest_due'] else None,
            'branches': ([{'branch': b['branch'], 'amount': _f(b['amount']), 'cost': _f(b['cost']), 'profit': _f(b['amount'] - b['cost'])}
                          for b in c['branches'].values()] if len(c['branches']) > 1 or 'Head office' not in c['branches'] else []),
        })

    for r in rows_inv:                      # strip internals before returning
        for k in [k for k in r if k.startswith('_')]:
            del r[k]

    return {
        'period': {'start': start.isoformat(), 'end': end.isoformat(), 'label': label, 'kind': period},
        'basis': basis, 'basis_label': BASIS_LABELS[basis], 'as_of': as_of.isoformat(),
        'generated_at': None,
        'headline': headline, 'equation': equation,
        'sections': {
            'revenue': {'label': rev_label, 'amount': _f(revenue_total), 'explain': explain['revenue'], 'invoices': rows_inv,
                        'direct_sales': [{'ref': t.payment_method.upper(), 'label': t.description, 'date': t.created_at.date().isoformat(),
                                          'amount': _f(t.amount), 'url': '/portal/dashboard/cash-management/'} for t in direct],
                        'invoices_amount': _f(invoice_total), 'direct_amount': _f(direct_total)},
            'provider_costs': {'label': 'Service-provider costs', 'amount': _f(provider_total), 'explain': explain['provider_costs'], 'rows': prov_rows},
            'running_costs': {'label': 'Running costs', 'amount': _f(running_total), 'explain': explain['running_costs'],
                              'rows': running_rows, 'recurring': templates},
            'payroll': {'label': 'Payroll', 'amount': _f(payroll_total), 'explain': explain['payroll'], 'rows': payroll_rows},
        },
        'warnings': warnings, 'clients': client_rows,
    }

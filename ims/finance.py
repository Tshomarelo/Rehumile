"""
Single source of truth for "how is the business doing?".

Every number on the HQ Dashboard and on Business Intelligence comes from this
module, so the two can never disagree. Each figure is returned together with
the *workings* (which records it is made of) so the UI can show exactly how
the answer was reached.

Definitions (all amounts exclude VAT, because VAT belongs to SARS, not us):

  Invoiced   = invoices issued (sent / paid / overdue) in the period
  Paid       = invoices whose payment date falls in the period   -> revenue
  Unpaid     = invoices issued but not yet paid (sent / overdue), owed to us
  Revenue    = Paid invoices (ex VAT) + direct sales (POS, cash)
  Expenses   = cost of goods + operating expenses recorded in the period
               + the cost of the services (WiFi/Axxess, email, hosting) on the invoices that were paid
               + payroll cost (gross pay + employer UIF/SDL) of approved payroll
  Profit     = Revenue - Expenses
  Capital purchases (equipment, tools) are assets, not expenses: they are
  shown separately and NOT deducted from profit.
"""
import calendar
from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Q, Sum

from . import costlines
from .timeutils import since, until
from .models import (
    CashTransaction, Expense, ExpenseCategory, Invoice, InvoicePayment, PayrollEntry,
)

ZERO = Decimal('0')


def _today():
    from . import billing          # one clock for the whole app (tests pin it)
    return billing._today()
ROW_LIMIT = 100  # cap on drill-down rows returned per step


def _f(value):
    """Decimal/None -> float rounded to cents (JSON friendly)."""
    return round(float(value or 0), 2)


# ─────────────────────────────────────────────────────────────────────────────
# Periods
# ─────────────────────────────────────────────────────────────────────────────

def week_start(d):
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()


def resolve_period(period='month', anchor=None, date_from=None, date_to=None, today=None):
    """Return (start, end, label) for period in week|month|quarter|year|custom."""
    today = today or _today()
    anchor = parse_date(anchor) or today
    if period == 'custom':
        start, end = parse_date(date_from), parse_date(date_to)
        if not start or not end:
            raise ValueError('date_from and date_to are required for a custom period.')
        if end < start:
            start, end = end, start
        return start, end, f"{start:%d %b %Y} – {end:%d %b %Y}"
    if period == 'week':
        start = week_start(anchor)
        end = start + timedelta(days=6)
        return start, end, f"Week of {start:%d %b %Y}"
    if period == 'quarter':
        q = (anchor.month - 1) // 3
        start = date(anchor.year, q * 3 + 1, 1)
        em = q * 3 + 3
        end = date(anchor.year, em, calendar.monthrange(anchor.year, em)[1])
        return start, end, f"Q{q + 1} {anchor.year}"
    if period == 'year':
        return date(anchor.year, 1, 1), date(anchor.year, 12, 31), str(anchor.year)
    # month (default)
    start = anchor.replace(day=1)
    end = anchor.replace(day=calendar.monthrange(anchor.year, anchor.month)[1])
    return start, end, f"{start:%B %Y}"


# ─────────────────────────────────────────────────────────────────────────────
# Querysets — each business rule lives in exactly one place
# ─────────────────────────────────────────────────────────────────────────────

class _Portion:
    """One payment's share of an invoice: behaves like the invoice but with its money fields scaled by `frac`."""

    def __init__(self, invoice, pay_date, frac, key):
        self._inv, self.frac, self.id = invoice, frac, key
        self.payment_date = pay_date
        self.subtotal = invoice.subtotal * frac
        self.tax_amount = invoice.tax_amount * frac
        self.total_amount = invoice.total_amount * frac

    def __getattr__(self, name):
        return getattr(self._inv, name)


def _paid_events(start, end):
    """
    Money received in the window as invoice portions. Each recorded payment (full or part) counts on its own
    date for its share of the invoice; older invoices marked paid without payment records count in full on
    their payment date.
    """
    events = []
    pays = (InvoicePayment.objects.filter(payment_date__gte=start, payment_date__lte=end)
            .exclude(invoice__status='cancelled').select_related('invoice', 'invoice__company', 'invoice__wifi_subscriber', 'invoice__sla_contract')
            .prefetch_related('invoice__items'))
    for p in pays:
        total = p.invoice.total_amount
        frac = (p.amount / total) if total else Decimal('1')
        events.append(_Portion(p.invoice, p.payment_date, frac, p.id))
    legacy = (Invoice.objects.filter(status='paid', payment_date__gte=start, payment_date__lte=end, payment_records__isnull=True)
              .select_related('company', 'wifi_subscriber', 'sla_contract').prefetch_related('items'))
    for inv in legacy:
        events.append(_Portion(inv, inv.payment_date, Decimal('1'), inv.id))
    events.sort(key=lambda e: e.payment_date, reverse=True)
    return events


def _invoiced_qs(start, end):
    return Invoice.objects.filter(
        status__in=('sent', 'partially_paid', 'paid', 'overdue'),
        **since('sent_at', start), **until('sent_at', end),
    )


OPEN_STATUSES = ('sent', 'partially_paid', 'overdue')


def _unpaid_qs(as_of):
    """
    THE definition of "unpaid": issued (sent / part-paid / overdue) on or before `as_of` and not yet fully paid.
    Everything that talks about money owed (dashboard, Business Intelligence, the Profit & Money Owed report)
    uses this one rule; a slice by billing period is applied on top, never a different definition.
    """
    return Invoice.objects.filter(
        status__in=('sent', 'partially_paid', 'overdue'), **until('sent_at', as_of),
    )


def _direct_sales_qs(start, end):
    # CashTransactions attached to an invoice are the *payment* of that
    # invoice (already counted under Paid) — only count the ones without.
    return CashTransaction.objects.filter(
        transaction_category='sale', invoice__isnull=True,
        **since('created_at', start), **until('created_at', end),
    )


def _expense_qs(start, end):
    """Expenses that count as costs in profit. Supplier account bills are left out: the cost of the client lines
    on them is already counted through the invoices, and our own lines are recurring costs."""
    return Expense.objects.filter(expense_date__gte=start, expense_date__lte=end, is_supplier_bill=False)


def _payroll_qs(start, end):
    return PayrollEntry.objects.filter(
        is_frozen=True,
        compliance_period__period_end__gte=start, compliance_period__period_end__lte=end,
    )


def _client_name(inv):
    if inv.company_id and inv.company:
        return inv.company.name
    if inv.bill_to_name:
        return inv.bill_to_name
    if inv.wifi_subscriber_id and inv.wifi_subscriber:
        return inv.wifi_subscriber.client_name
    if inv.sla_contract_id and inv.sla_contract:
        return inv.sla_contract.client_name
    return inv.description or '—'


def invoice_split(inv):
    """
    How one invoice divides into revenue streams and costs (all ex VAT).
    Combined 'subscription' invoices are split line by line by service; older invoices by type.
    Returns {'streams': {'wifi'|'sla'|'adhoc'|'services': amount}, 'axxess': cost, 'services_cost': cost}.
    """
    split = _raw_split(inv)
    frac = getattr(inv, 'frac', None)
    if frac is not None and frac != 1:
        split = {'streams': {k: v * frac for k, v in split['streams'].items()},
                 'axxess': split['axxess'] * frac, 'services_cost': split['services_cost'] * frac}
    return split


def _raw_split(inv):
    streams, axxess, svc_cost = {}, ZERO, ZERO
    if inv.invoice_type == 'subscription' and inv.items.all():
        for it in inv.items.all():
            stream = it.service_type if it.service_type in ('wifi', 'sla') else 'services'
            streams[stream] = streams.get(stream, ZERO) + it.amount
            cost = (it.quantity or ZERO) * (it.unit_cost or ZERO)
            if it.service_type == 'wifi':
                axxess += cost
            else:
                svc_cost += cost
        return {'streams': streams, 'axxess': axxess, 'services_cost': svc_cost}
    stream = {'wifi': 'wifi', 'sla': 'sla', 'callout': 'sla', 'subscription': 'services'}.get(inv.invoice_type, 'adhoc')
    streams[stream] = inv.subtotal
    if inv.invoice_type == 'wifi':
        axxess = inv.wholesale_cost or ZERO
    else:
        # ad-hoc / job invoices: the optional "Your cost" on each line is the cost of the job
        svc_cost = sum(((it.quantity or ZERO) * (it.unit_cost or ZERO) for it in inv.items.all()), ZERO)
        if not svc_cost and inv.invoice_type == 'subscription':
            svc_cost = inv.wholesale_cost or ZERO
    return {'streams': streams, 'axxess': axxess, 'services_cost': svc_cost}


def paid_by_stream(start, end):
    """Money received in the window, ex VAT, split wifi / sla / adhoc / services."""
    out = {'wifi': ZERO, 'sla': ZERO, 'adhoc': ZERO, 'services': ZERO}
    for inv in _paid_events(start, end):
        for k, v in invoice_split(inv)['streams'].items():
            out[k] += v
    return {k: float(v) for k, v in out.items()}


def is_from_period(inv, start, end):
    """An unpaid invoice is 'from this period' when its billing period starts inside it; otherwise it is earlier."""
    return bool(inv.billing_period_start and start <= inv.billing_period_start <= end)


def outstanding_by_stream(start, end, as_of=None, scope='period'):
    """
    Money still owed (incl. VAT, apportioned by line), split by stream. Uses the single unpaid rule
    (_unpaid_qs); scope = 'period' (billing period inside the window), 'earlier' or 'all'.
    """
    out = {'wifi': ZERO, 'sla': ZERO, 'adhoc': ZERO, 'services': ZERO}
    qs = [i for i in _unpaid_qs(as_of or min(end, _today())).prefetch_related('items')
          if scope == 'all' or (is_from_period(i, start, end) == (scope == 'period'))]
    for inv in qs:
        split = invoice_split(inv)['streams']
        base = sum(split.values(), ZERO) or ZERO
        due = inv.balance_due
        for k, v in split.items():
            out[k] += (due * v / base) if base else due
    return {k: float(v) for k, v in out.items()}


def _invoice_row(inv, date_value, include_total=False):
    row = {
        'ref': inv.invoice_number,
        'label': _client_name(inv),
        'date': date_value.isoformat() if date_value else None,
        'amount': _f(inv.subtotal),
        'url': f"/portal/invoices/?search={inv.invoice_number}",
    }
    if include_total:
        row['total'] = _f(inv.total_amount)
    return row


# ─────────────────────────────────────────────────────────────────────────────
# Summary with workings
# ─────────────────────────────────────────────────────────────────────────────

def summary(start, end, today=None):
    today = today or _today()

    # ── Invoices ────────────────────────────────────────────────────────────
    paid_invoices = _paid_events(start, end)
    paid_sub = sum((i.subtotal for i in paid_invoices), ZERO)
    paid_vat = sum((i.tax_amount for i in paid_invoices), ZERO)
    paid_total = sum((i.total_amount for i in paid_invoices), ZERO)

    invoiced_agg = _invoiced_qs(start, end).aggregate(s=Sum('subtotal'), v=Sum('tax_amount'), t=Sum('total_amount'))
    invoiced_count = _invoiced_qs(start, end).count()

    unpaid_invoices = list(_unpaid_qs(min(end, today))
                           .select_related('company', 'wifi_subscriber', 'sla_contract').order_by('due_date', 'sent_at'))
    unpaid_total = sum((i.balance_due for i in unpaid_invoices), ZERO)
    unpaid_from_period = sum((i.balance_due for i in unpaid_invoices if is_from_period(i, start, end)), ZERO)
    unpaid_earlier = unpaid_total - unpaid_from_period
    overdue = [i for i in unpaid_invoices if i.status == 'overdue' or (i.due_date and i.due_date < today)]
    overdue_total = sum((i.balance_due for i in overdue), ZERO)

    # ── Direct sales ────────────────────────────────────────────────────────
    direct = list(_direct_sales_qs(start, end).order_by('-created_at'))
    direct_total = sum((t.amount for t in direct), ZERO)

    revenue = paid_sub + direct_total

    # ── Expenses ────────────────────────────────────────────────────────────
    expenses = list(_expense_qs(start, end).select_related('expense_category', 'account').order_by('-expense_date'))
    by_cat = OrderedDict()
    cogs_exp = opex_exp = capital_exp = unpaid_exp = ZERO
    for e in expenses:
        name = e.expense_category.name if e.expense_category_id else e.account.name
        c = by_cat.setdefault(name, {'name': name, 'kind': e.category, 'amount': ZERO, 'paid': ZERO, 'unpaid': ZERO, 'count': 0,
                                      'category_id': str(e.expense_category_id) if e.expense_category_id else None})
        c['amount'] += e.amount
        c['count'] += 1
        if e.payment_status == 'paid':
            c['paid'] += e.amount
        else:
            c['unpaid'] += e.amount
            unpaid_exp += e.amount
        if e.category == 'cogs':
            cogs_exp += e.amount
        elif e.category == 'capital':
            capital_exp += e.amount
        else:
            opex_exp += e.amount

    splits = {i.id: invoice_split(i) for i in paid_invoices}
    axxess_cost = sum((sp['axxess'] for sp in splits.values()), ZERO)
    service_cost = sum((sp['services_cost'] for sp in splits.values()), ZERO)

    payroll_entries = list(_payroll_qs(start, end).select_related('employee', 'compliance_period'))
    payroll_cost = sum((p.employer_cost for p in payroll_entries), ZERO)
    payroll_draft = PayrollEntry.objects.filter(
        is_frozen=False,
        compliance_period__period_end__gte=start, compliance_period__period_end__lte=end,
    ).aggregate(t=Sum('total_gross'))['t'] or ZERO

    cost_of_sales = axxess_cost + service_cost + cogs_exp
    gross_profit = revenue - cost_of_sales
    total_expenses = cost_of_sales + opex_exp + payroll_cost
    net_profit = revenue - total_expenses

    # ── Workings (the "how did we get here" trail) ─────────────────────────
    workings = [
        {'key': 'paid_invoices', 'label': 'Paid invoices (excl. VAT)', 'sign': '+', 'amount': _f(paid_sub),
         'explain': f"{len(paid_invoices)} payment(s) received between {start:%d %b} and {end:%d %b %Y} (part payments count for their share of the invoice). "
                    f"Total received was R {_f(paid_total):,.2f}; R {_f(paid_vat):,.2f} of that is VAT and is not our income.",
         'rows': [_invoice_row(i, i.payment_date) for i in paid_invoices[:ROW_LIMIT]]},
        {'key': 'direct_sales', 'label': 'Direct sales (POS / till, cash)', 'sign': '+', 'amount': _f(direct_total),
         'explain': f"{len(direct)} sale(s) taken at the till with no invoice behind them.",
         'rows': [{'ref': t.payment_method.upper(), 'label': t.description, 'date': t.created_at.date().isoformat(),
                   'amount': _f(t.amount), 'url': '/portal/dashboard/cash-management/'} for t in direct[:ROW_LIMIT]]},
        {'key': 'revenue', 'label': 'REVENUE', 'sign': '=', 'amount': _f(revenue), 'total': True,
         'explain': 'Paid invoices + direct sales. Money that has actually reached the business.'},
        {'key': 'axxess', 'label': 'Axxess wholesale cost (WiFi)', 'sign': '−', 'amount': _f(axxess_cost),
         'explain': 'What Axxess charged us for the WiFi lines on the paid WiFi invoices above (taken from each invoice).',
         'rows': [{'ref': i.invoice_number, 'label': _client_name(i), 'date': i.payment_date.isoformat() if i.payment_date else None,
                   'amount': _f(splits[i.id]['axxess']), 'url': f"/portal/invoices/?search={i.invoice_number}"}
                  for i in paid_invoices if splits[i.id]['axxess']][:ROW_LIMIT]},
        {'key': 'service_costs', 'label': 'Email / hosting / other service costs', 'sign': '−', 'amount': _f(service_cost),
         'explain': 'What your email, hosting and other subscription services cost you, for the subscription invoices paid in this period (taken from each invoice line).',
         'rows': [{'ref': i.invoice_number, 'label': _client_name(i), 'date': i.payment_date.isoformat() if i.payment_date else None,
                   'amount': _f(splits[i.id]['services_cost']), 'url': f"/portal/invoices/?search={i.invoice_number}"}
                  for i in paid_invoices if splits[i.id]['services_cost']][:ROW_LIMIT]},
        {'key': 'cogs', 'label': 'Cost of goods (parts & stock bought)', 'sign': '−', 'amount': _f(cogs_exp),
         'explain': 'Expenses in a "Cost of Goods" category — stock and parts bought to resell or use on jobs.',
         'rows': _expense_rows(expenses, 'cogs')},
        {'key': 'gross_profit', 'label': 'GROSS PROFIT', 'sign': '=', 'amount': _f(gross_profit), 'total': True,
         'explain': 'Revenue minus what it cost to deliver it.'},
        {'key': 'opex', 'label': 'Operating expenses', 'sign': '−', 'amount': _f(opex_exp),
         'explain': 'Running costs recorded in the period (rent, data, fuel, …). An expense counts when it is incurred, even if the supplier is still '
                    f"unpaid (R {_f(unpaid_exp):,.2f} of this period's expenses are unpaid).",
         'rows': _expense_rows(expenses, 'operating')},
        {'key': 'payroll', 'label': 'Payroll (salaries + employer UIF/SDL)', 'sign': '−', 'amount': _f(payroll_cost),
         'explain': f"{len(payroll_entries)} approved payslip(s) for pay months ending in this period."
                    + (f" R {_f(payroll_draft):,.2f} of draft payroll is not included until approved." if payroll_draft else ''),
         'rows': [{'ref': p.employee.employee_number, 'label': f"{p.employee.first_name} {p.employee.last_name}",
                   'date': p.compliance_period.period_end.isoformat(), 'amount': _f(p.employer_cost),
                   'url': '/portal/dashboard/hr/#payroll'} for p in payroll_entries[:ROW_LIMIT]]},
        {'key': 'net_profit', 'label': 'NET PROFIT', 'sign': '=', 'amount': _f(net_profit), 'total': True,
         'explain': 'Revenue minus all expenses. Capital purchases are excluded — see the note below.'},
    ]

    return {
        'period': {'start': start.isoformat(), 'end': end.isoformat()},
        'invoices': {
            'invoiced': {'count': invoiced_count, 'subtotal': _f(invoiced_agg['s']), 'vat': _f(invoiced_agg['v']), 'total': _f(invoiced_agg['t'])},
            'paid': {'count': len(paid_invoices), 'subtotal': _f(paid_sub), 'vat': _f(paid_vat), 'total': _f(paid_total)},
            'unpaid': {
                'count': len(unpaid_invoices), 'total': _f(unpaid_total),
                'from_period': _f(unpaid_from_period), 'from_earlier': _f(unpaid_earlier),
                'overdue_count': len(overdue), 'overdue_total': _f(overdue_total),
                'rows': [dict(_invoice_row(i, i.due_date or (i.sent_at.date() if i.sent_at else None), include_total=True),
                              amount=_f(i.balance_due), overdue=(i in overdue))
                         for i in unpaid_invoices[:ROW_LIMIT]],
            },
        },
        'revenue': {'invoices': _f(paid_sub), 'direct_sales': _f(direct_total), 'total': _f(revenue)},
        'expenses': {
            'cost_of_sales': _f(cost_of_sales), 'axxess': _f(axxess_cost), 'service_costs': _f(service_cost), 'cogs': _f(cogs_exp),
            'operating': _f(opex_exp), 'payroll': _f(payroll_cost), 'total': _f(total_expenses),
            'unpaid_to_suppliers': _f(unpaid_exp),
            'capital_purchases': _f(capital_exp),
            'by_category': [dict(c, amount=_f(c['amount']), paid=_f(c['paid']), unpaid=_f(c['unpaid']))
                            for c in sorted(by_cat.values(), key=lambda x: -x['amount'])],
        },
        'profit': {
            'gross': _f(gross_profit), 'net': _f(net_profit),
            'margin_pct': round(float(net_profit / revenue * 100), 1) if revenue else 0,
        },
        'accrual': accrual_summary(start, end, today),
        'workings': workings,
        'notes': [
            'Capital purchases (equipment/tools) of R %s are assets, so they are not deducted from profit.' % f"{_f(capital_exp):,.2f}",
            'Axxess wholesale cost is taken automatically from WiFi invoices — do not also enter it as an expense.',
            'Payroll is booked in the pay month it belongs to, so it shows in the week/month/year containing that month-end.',
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Accrual view: "profit if every invoice is paid"
# ─────────────────────────────────────────────────────────────────────────────

def _issued(start, end):
    return list(_invoiced_qs(start, end).select_related('company', 'wifi_subscriber', 'sla_contract').prefetch_related('items__subscription'))


def accrual_summary(start, end, today=None):
    """
    The accrual picture of a period: revenue = invoices issued in it (excl. VAT) + till sales; cost of sales = the full
    Axxess / service / job cost of those invoices whether or not they are paid, plus parts bought; then running costs
    and payroll. Also explains the gap to "profit on money collected" (the cash-style figure the dashboard shows).
    """
    issued = _issued(start, end)
    events = _paid_events(start, end)
    recv = {}
    for ev in events:
        recv[ev._inv.id] = recv.get(ev._inv.id, ZERO) + ev.frac
    issued_ids = {i.id for i in issued}

    inv_rev = sum((i.subtotal for i in issued), ZERO)
    splits = {i.id: invoice_split(i) for i in issued}
    inv_cost = sum((sp['axxess'] + sp['services_cost'] for sp in splits.values()), ZERO)
    direct_total = sum((t.amount for t in _direct_sales_qs(start, end)), ZERO)
    expenses = list(_expense_qs(start, end))
    cogs = sum((e.amount for e in expenses if e.category == 'cogs'), ZERO)
    opex = sum((e.amount for e in expenses if e.category not in ('cogs', 'capital')), ZERO)
    payroll = sum((p.employer_cost for p in _payroll_qs(start, end)), ZERO)
    revenue = inv_rev + direct_total
    cost_of_sales = inv_cost + cogs
    gross = revenue - cost_of_sales
    net = gross - opex - payroll

    # this period's invoices that have not been (fully) paid within the period, and what they cost
    a_rev = a_cost = ZERO
    not_counted_rows = []
    for inv in issued:
        frac = max(ZERO, Decimal('1') - recv.get(inv.id, ZERO))
        if frac <= 0:
            continue
        a_rev += inv.subtotal * frac
        sp = splits[inv.id]
        inv_c = (sp['axxess'] + sp['services_cost']) * frac
        a_cost += inv_c
        for ln in costlines.lines(inv):
            c = ln['cost'] * frac
            if c:
                not_counted_rows.append({
                    'ref': inv.invoice_number, 'label': _client_name(inv), 'line': ln['description'], 'branch': ln['site_name'],
                    'amount': _f(c), 'revenue': _f(ln['amount'] * frac), 'source': costlines.line_source(inv, ln, c),
                    'date': inv.sent_at.date().isoformat() if inv.sent_at else None,
                    'paid': inv.status == 'paid', 'url': costlines.invoice_link(inv)})
    # money collected in this period for invoices issued earlier (their revenue and cost count in the collected view only)
    b_rev = b_cost = ZERO
    for ev in events:
        if ev._inv.id not in issued_ids:
            sp = invoice_split(ev)
            b_rev += ev.subtotal
            b_cost += sp['axxess'] + sp['services_cost']

    collected = summary_core_net(start, end)
    reconciliation = [
        {'key': 'unpaid_revenue', 'label': "Invoiced this period but not yet paid (excl. VAT)", 'sign': '+', 'amount': _f(a_rev),
         'explain': "Revenue on this period's invoices that clients have not paid yet. The collected figure ignores it."},
        {'key': 'unpaid_cost', 'label': "Their Axxess / service costs", 'sign': '−', 'amount': _f(a_cost),
         'explain': "What those same invoices cost us. The collected figure only counts a cost once the client has paid."},
        {'key': 'earlier_revenue', 'label': "Collected this period for invoices issued earlier (excl. VAT)", 'sign': '−', 'amount': _f(b_rev),
         'explain': "Money that arrived now for earlier months' invoices. It is in the collected figure but not in this period's invoicing."},
        {'key': 'earlier_cost', 'label': "Costs of those earlier invoices", 'sign': '+', 'amount': _f(b_cost),
         'explain': "The matching costs, counted in the collected figure when the money arrived."},
    ]
    gap = (a_rev - a_cost) - (b_rev - b_cost)
    return {
        'profit_if_paid': _f(net), 'profit_collected': _f(collected), 'gap': _f(net - collected), 'gap_check': _f(gap),
        'revenue': {'invoices': _f(inv_rev), 'direct_sales': _f(direct_total), 'total': _f(revenue), 'invoice_count': len(issued)},
        'cost_of_sales': {'invoice_costs': _f(inv_cost), 'parts': _f(cogs), 'total': _f(cost_of_sales)},
        'gross': _f(gross), 'operating': _f(opex), 'payroll': _f(payroll), 'net': _f(net),
        'margin_pct': round(float(net / revenue * 100), 1) if revenue else 0,
        'costs_not_counted': {'amount': _f(a_cost), 'revenue': _f(a_rev), 'rows': not_counted_rows[:ROW_LIMIT]},
        'reconciliation': reconciliation,
        'explain': {
            'profit_collected': "Profit on money collected: payments received in the period (excl. VAT) minus the Axxess/service costs of those paid invoices, minus running costs and payroll.",
            'profit_if_paid': "Profit if all invoices are paid: every invoice issued in the period (excl. VAT) minus ALL of their Axxess/service costs (paid or not), minus running costs and payroll.",
        },
    }


def summary_core_net(start, end):
    """Net profit on money collected (the dashboard's number), without building the whole summary."""
    events = _paid_events(start, end)
    revenue = sum((e.subtotal for e in events), ZERO) + sum((t.amount for t in _direct_sales_qs(start, end)), ZERO)
    cost = ZERO
    for e in events:
        sp = invoice_split(e)
        cost += sp['axxess'] + sp['services_cost']
    expenses = list(_expense_qs(start, end))
    cogs = sum((x.amount for x in expenses if x.category == 'cogs'), ZERO)
    opex = sum((x.amount for x in expenses if x.category not in ('cogs', 'capital')), ZERO)
    payroll = sum((p.employer_cost for p in _payroll_qs(start, end)), ZERO)
    return revenue - cost - cogs - opex - payroll


def _expense_rows(expenses, kind):
    return [{'ref': e.vendor, 'label': (e.expense_category.name if e.expense_category_id else e.account.name)
             + (f" — {e.description}" if e.description else '') + ('' if e.payment_status == 'paid' else ' (unpaid)'),
             'date': e.expense_date.isoformat(), 'amount': _f(e.amount), 'url': '/portal/dashboard/expenses/'}
            for e in expenses if e.category == kind][:ROW_LIMIT]


# ─────────────────────────────────────────────────────────────────────────────
# Trend — weekly / monthly / yearly buckets
# ─────────────────────────────────────────────────────────────────────────────

def bucket_start(d, granularity):
    if granularity == 'weekly':
        return week_start(d)
    if granularity == 'yearly':
        return date(d.year, 1, 1)
    return d.replace(day=1)


def next_bucket(d, granularity):
    if granularity == 'weekly':
        return d + timedelta(days=7)
    if granularity == 'yearly':
        return date(d.year + 1, 1, 1)
    return date(d.year + (d.month // 12), d.month % 12 + 1, 1)


def bucket_label(d, granularity):
    if granularity == 'weekly':
        return f"{d:%d %b}"
    if granularity == 'yearly':
        return str(d.year)
    return f"{d:%b %Y}"


DEFAULT_PERIODS = {'weekly': 12, 'monthly': 12, 'yearly': 5}


def trend(granularity='monthly', periods=None, today=None, anchor=None):
    """Revenue / expenses / profit per bucket, ending at the bucket containing `anchor` (today)."""
    if granularity not in DEFAULT_PERIODS:
        raise ValueError('granularity must be weekly, monthly or yearly.')
    today = today or _today()
    anchor = parse_date(anchor) or today
    n = max(1, min(int(periods or DEFAULT_PERIODS[granularity]), 60))

    # build bucket starts (oldest -> newest)
    starts = [bucket_start(anchor, granularity)]
    for _ in range(n - 1):
        cur = starts[0]
        if granularity == 'weekly':
            prev = cur - timedelta(days=7)
        elif granularity == 'yearly':
            prev = date(cur.year - 1, 1, 1)
        else:
            prev = date(cur.year - (1 if cur.month == 1 else 0), 12 if cur.month == 1 else cur.month - 1, 1)
        starts.insert(0, prev)
    range_start = starts[0]
    range_end = next_bucket(starts[-1], granularity) - timedelta(days=1)

    buckets = OrderedDict((s, defaultdict(lambda: ZERO)) for s in starts)

    def add(d, key, amount):
        if d is None:
            return
        b = buckets.get(bucket_start(d, granularity))
        if b is not None:
            b[key] += amount

    for inv in _paid_events(range_start, range_end):
        sp = invoice_split(inv)
        for stream, amount in sp['streams'].items():
            add(inv.payment_date, 'rev_' + stream, amount)
            add(inv.payment_date, 'revenue', amount)
        if sp['axxess']:
            add(inv.payment_date, 'cost_axxess', sp['axxess'])
        if sp['services_cost']:
            add(inv.payment_date, 'cost_services', sp['services_cost'])
    for t in _direct_sales_qs(range_start, range_end):
        add(t.created_at.date(), 'rev_direct', t.amount)
        add(t.created_at.date(), 'revenue', t.amount)
    for inv in _invoiced_qs(range_start, range_end):
        add(inv.sent_at.date(), 'invoiced', inv.subtotal)
    for e in _expense_qs(range_start, range_end):
        if e.category == 'capital':
            add(e.expense_date, 'capital', e.amount)
        else:
            add(e.expense_date, 'cost_expenses', e.amount)
    for p in _payroll_qs(range_start, range_end).select_related('compliance_period'):
        add(p.compliance_period.period_end, 'cost_payroll', p.employer_cost)

    rows = []
    for s, b in buckets.items():
        e = next_bucket(s, granularity) - timedelta(days=1)
        expenses = b['cost_axxess'] + b['cost_services'] + b['cost_expenses'] + b['cost_payroll']
        profit = b['revenue'] - expenses
        rows.append({
            'label': bucket_label(s, granularity), 'start': s.isoformat(), 'end': e.isoformat(),
            'revenue': _f(b['revenue']), 'invoiced': _f(b['invoiced']),
            'expenses': _f(expenses), 'profit': _f(profit),
            'rev_wifi': _f(b['rev_wifi']), 'rev_sla': _f(b['rev_sla']),
            'rev_adhoc': _f(b['rev_adhoc']), 'rev_direct': _f(b['rev_direct']), 'rev_services': _f(b['rev_services']),
            'cost_axxess': _f(b['cost_axxess']), 'cost_services': _f(b['cost_services']), 'cost_expenses': _f(b['cost_expenses']),
            'cost_payroll': _f(b['cost_payroll']), 'capital': _f(b['capital']),
        })
    tot_rev = sum((r['revenue'] for r in rows), 0.0)
    tot_exp = sum((r['expenses'] for r in rows), 0.0)
    return {
        'granularity': granularity,
        'range': {'start': range_start.isoformat(), 'end': range_end.isoformat()},
        'buckets': rows,
        'totals': {'revenue': round(tot_rev, 2), 'expenses': round(tot_exp, 2), 'profit': round(tot_rev - tot_exp, 2),
                   'invoiced': round(sum(r['invoiced'] for r in rows), 2)},
    }

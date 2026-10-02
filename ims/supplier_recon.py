"""
Supplier account reconciliation (Axxess): what the supplier charges per account versus what our own system has recorded, line by line.

Counting rule (no double counting): the cost of a CLIENT line is counted through that client's invoices only (the service's cost per
month). Our OWN lines (e.g. the owner's house) are recurring costs. A supplier bill logged as an expense is excluded from profit and
exists to say what is owed / what was paid and what the supplier charged per line.
"""
from decimal import Decimal

from . import billing
from .models import Expense, RecurringExpense, Subscription, SupplierAccount

ZERO = Decimal('0')
STEP = {'monthly': Decimal('1'), 'quarterly': Decimal('3'), 'annual': Decimal('12')}


def _f(v):
    return round(float(v or 0), 2)


def _month(month, today):
    if month:
        y, m = (int(x) for x in str(month)[:7].split('-'))
    else:
        y, m = today.year, today.month
    return billing.month_bounds(y, m)


def reconcile(month=None, today=None):
    today = today or billing._today()
    start, end = _month(month, today)
    accounts = []
    for acct in SupplierAccount.objects.all():
        subs = list(Subscription.objects.select_related('company', 'site').filter(supplier_account=acct, status='active', start_date__lte=end)
                    .exclude(end_date__lt=start))
        owns = list(RecurringExpense.objects.filter(supplier_account=acct, is_active=True, start_date__lte=end))
        bill = (Expense.objects.filter(supplier_account=acct, is_supplier_bill=True, expense_date__gte=start, expense_date__lte=end)
                .prefetch_related('lines').order_by('-expense_date', '-created_at').first())
        charged_by_sub, charged_by_rec, unlinked = {}, {}, []
        if bill:
            for l in bill.lines.all():
                if l.subscription_id:
                    charged_by_sub[l.subscription_id] = charged_by_sub.get(l.subscription_id, ZERO) + l.amount
                elif l.recurring_expense_id:
                    charged_by_rec[l.recurring_expense_id] = charged_by_rec.get(l.recurring_expense_id, ZERO) + l.amount
                else:
                    unlinked.append(l)
        rows = []
        for s in subs:
            rec = (s.quantity or ZERO) * (s.unit_cost or ZERO)
            ch = charged_by_sub.get(s.id)
            rows.append({'kind': 'client', 'label': f"{s.client_label}{' — ' + s.site.name if s.site_id else ''} — {s.description or s.get_service_type_display()}",
                         'axxess_id': s.axxess_id, 'recorded': _f(rec), 'charged': _f(ch) if ch is not None else None,
                         'diff': _f(ch - rec) if ch is not None else None, 'counted_via': 'client invoice', 'url': '/portal/dashboard/subscriptions/#services'})
        for r in owns:
            rec = r.amount / STEP[r.frequency]
            ch = charged_by_rec.get(r.id)
            rows.append({'kind': 'own', 'label': r.name, 'axxess_id': '', 'recorded': _f(rec), 'charged': _f(ch) if ch is not None else None,
                         'diff': _f(ch - rec) if ch is not None else None, 'counted_via': 'our own recurring cost', 'url': '/portal/dashboard/expenses/#recurring'})
        for l in unlinked:
            rows.append({'kind': 'unlinked', 'label': f"On the bill but not linked to a line: {l.description}", 'axxess_id': '', 'recorded': 0.0,
                         'charged': _f(l.amount), 'diff': _f(l.amount), 'counted_via': 'not counted anywhere', 'url': '/portal/dashboard/expenses/'})
        recorded_total = sum((Decimal(str(r['recorded'])) for r in rows), ZERO)
        charged_total = bill.amount if bill else acct.charged_total
        diff = (charged_total - recorded_total) if charged_total is not None else None
        differing = [r for r in rows if r['diff'] not in (None, 0.0)]
        if not rows:
            explain = 'No lines are assigned to this account yet. Set the Axxess account on each service (Subscriptions > Services) and on your own recurring costs.'
        elif diff is None:
            explain = 'Enter what Axxess charges on this account (or log the bill) to compare it with our records.'
        elif abs(diff) < Decimal('0.005'):
            explain = 'Axxess charges exactly what we have recorded.'
        else:
            who = (' Lines that differ: ' + '; '.join(f"{r['label']} (charged R{r['charged']:,.2f}, recorded R{r['recorded']:,.2f})" for r in differing) + '.') if differing else \
                  ' Log the bill with its per-line amounts to see which line differs.'
            explain = (f"Axxess charges R{abs(diff):,.2f} {'more' if diff > 0 else 'less'} than our records." + who +
                       ' Check the line price against the Axxess invoice (cost per month on the service).')
        accounts.append({
            'id': str(acct.id), 'supplier': acct.supplier, 'account_number': acct.account_number, 'name': acct.name,
            'charged_source': 'bill' if bill else ('account total' if acct.charged_total is not None else None),
            'bill_id': str(bill.id) if bill else None, 'bill_status': bill.payment_status if bill else None,
            'charged': _f(charged_total) if charged_total is not None else None, 'recorded': _f(recorded_total),
            'difference': _f(diff) if diff is not None else None, 'explain': explain, 'lines': rows,
        })
    # WiFi lines that carry an Axxess id but belong to no account yet
    unassigned = [{'label': f"{s.client_label} — {s.description or s.get_service_type_display()}", 'axxess_id': s.axxess_id, 'recorded': _f((s.quantity or ZERO) * (s.unit_cost or ZERO))}
                  for s in Subscription.objects.select_related('company').filter(status='active', service_type='wifi', supplier_account__isnull=True).exclude(axxess_id='')]
    return {
        'month': start.strftime('%Y-%m'), 'accounts': accounts, 'unassigned_lines': unassigned,
        'totals': {'charged': _f(sum((Decimal(str(a['charged'] or 0)) for a in accounts), ZERO)), 'recorded': _f(sum((Decimal(str(a['recorded'])) for a in accounts), ZERO))},
        'rule': 'Client-line costs are counted through the invoices only. Only our own lines are recurring costs. Supplier bills are never counted again as a cost.',
    }

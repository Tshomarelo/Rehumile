"""
Monthly billing run.

Every active Subscription that is due in the month is grouped by WHO PAYS and turned into a
single invoice with one line per service and one total:

  * A branch set to "Branch pays its own invoice" gets its own invoice.
  * Everything else (head-office services and branches billed to head office) is combined on
    the head-office invoice, with each line tagged by branch so the invoice can show headings.
  * Direct-pay clients without a registered company are grouped by client name.

Running it twice never double-bills: a subscription that already has a line on a live invoice
for the month is skipped, so a late-added service only produces an invoice for that service.

Generated invoices carry no VAT unless a `vat_rate` (percent) is passed.
"""
import calendar
from collections import OrderedDict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from .models import Invoice, InvoiceItem, Subscription

CENT = Decimal('0.01')
SERVICE_LABELS = {
    'wifi': 'WiFi / Internet', 'email': 'Email hosting', 'hosting': 'Website hosting',
    'sla': 'SLA retainer', 'other': 'Other service',
}


def month_bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _money(v):
    return Decimal(v).quantize(CENT, ROUND_HALF_UP)


def _next_invoice_number(period_start):
    """INV-YYYY-MM-NNN, continuing after the highest number already used this month."""
    prefix = f"INV-{period_start.year}-{period_start.month:02d}-"
    used = Invoice.objects.filter(invoice_number__startswith=prefix).values_list('invoice_number', flat=True)
    top = 0
    for n in used:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            top = max(top, int(tail))
    return f"{prefix}{top + 1:03d}"


def _billed_subscription_ids(period_start, period_end):
    """Subscriptions that already have a line on a live (not cancelled) invoice for this period."""
    return set(
        InvoiceItem.objects.filter(
            subscription__isnull=False, invoice__billing_period_start=period_start,
            invoice__billing_period_end=period_end, invoice__invoice_type='subscription',
        ).exclude(invoice__status='cancelled').values_list('subscription_id', flat=True)
    )


def _group_key(sub):
    """(kind, id, site_id): who receives the invoice."""
    if sub.company_id:
        if sub.site_id and sub.site.billing_mode == 'self':
            return ('company', str(sub.company_id), str(sub.site_id))
        return ('company', str(sub.company_id), None)
    return ('name', (sub.client_name or '').strip().lower(), None)


def _line(sub):
    label = SERVICE_LABELS.get(sub.service_type, sub.get_service_type_display())
    desc = (sub.description or '').strip()
    text = label if not desc or desc.lower() == label.lower() else f"{label} — {desc}"
    site_name = sub.site.name if sub.site_id else ''
    return {
        'subscription_id': str(sub.id), 'service_type': sub.service_type, 'description': text[:255],
        'site_name': site_name, 'quantity': sub.quantity, 'unit_price': sub.unit_price,
        'unit_cost': sub.unit_cost, 'amount': _money(Decimal(sub.quantity) * Decimal(sub.unit_price)),
        'billing_day': sub.billing_day,
    }


def _recipients(company, site, subs):
    """Who gets the email: the branch contact for a self-billing branch, otherwise the company's billing contact."""
    emails = []
    if site is not None and site.contact_email:
        emails.append(site.contact_email)
    if company is not None:
        for e in (company.billing_email, company.contact_email):
            if e:
                emails.append(e)
    for s in subs:
        if s.contact_email:
            emails.append(s.contact_email)
    seen, out = set(), []
    for e in emails:
        if e.lower() not in seen:
            seen.add(e.lower())
            out.append(e)
        if site is not None and out:      # a branch that pays itself only gets mail for itself
            break
    return out[:2]


def plan(year, month, vat_rate=0):
    """
    Work out what a run would create — changes nothing.
    Returns {'period': {...}, 'groups': [...], 'skipped': [...], 'totals': {...}}.
    """
    start, end = month_bounds(year, month)
    vat = Decimal(str(vat_rate or 0))
    billed = _billed_subscription_ids(start, end)
    subs = (Subscription.objects.select_related('company', 'site')
            .filter(status='active', start_date__lte=end).order_by('company__name', 'client_name', 'site__name', 'service_type'))
    groups, skipped = OrderedDict(), []
    for sub in subs:
        if sub.end_date and sub.end_date < start:
            continue                                      # contract finished before this month
        if sub.id in billed:
            skipped.append({'subscription_id': str(sub.id), 'client': sub.client_label, 'service': sub.get_service_type_display(),
                            'reason': 'Already invoiced for this month'})
            continue
        key = _group_key(sub)
        g = groups.setdefault(key, {'key': '|'.join(str(k or '') for k in key), 'company': sub.company, 'site': None,
                                    'client_name': sub.client_label, 'subs': [], 'lines': []})
        if key[2]:
            g['site'] = sub.site
            g['client_name'] = f"{sub.client_label} — {sub.site.name}"
        g['subs'].append(sub)
        g['lines'].append(_line(sub))

    out = []
    for g in groups.values():
        # head-office services first, then branches A-Z, so the invoice reads in a sensible order
        g['lines'].sort(key=lambda l: (l['site_name'] != '', l['site_name'].lower(), l['service_type']))
        subtotal = sum((l['amount'] for l in g['lines']), Decimal('0'))
        tax = _money(subtotal * vat / 100)
        due_day = min(min(l['billing_day'] for l in g['lines']), end.day)
        out.append({
            'key': g['key'], 'company_id': str(g['company'].id) if g['company'] else None,
            'site_id': str(g['site'].id) if g['site'] else None, 'client_name': g['client_name'],
            'branches': sorted({l['site_name'] for l in g['lines'] if l['site_name']}),
            'lines': [{**l, 'quantity': float(l['quantity']), 'unit_price': float(l['unit_price']),
                       'unit_cost': float(l['unit_cost']), 'amount': float(l['amount'])} for l in g['lines']],
            'subtotal': float(subtotal), 'vat_rate': float(vat), 'tax_amount': float(tax), 'total': float(subtotal + tax),
            'cost': float(sum((_money(l['quantity'] * l['unit_cost']) for l in g['lines']), Decimal('0'))),
            'due_date': date(year, month, due_day).isoformat(),
            'recipients': _recipients(g['company'], g['site'], g['subs']),
            '_subs': g['subs'], '_company': g['company'], '_site': g['site'],
        })
    return {
        'period': {'year': year, 'month': month, 'start': start.isoformat(), 'end': end.isoformat(),
                   'label': start.strftime('%B %Y')},
        'groups': out, 'skipped': skipped,
        'totals': {'invoices': len(out), 'lines': sum(len(g['lines']) for g in out),
                   'amount': round(sum(g['total'] for g in out), 2), 'skipped': len(skipped)},
    }


def public(plan_result):
    """The plan without the internal model objects (for JSON)."""
    return {**plan_result, 'groups': [{k: v for k, v in g.items() if not k.startswith('_')} for g in plan_result['groups']]}


@transaction.atomic
def generate(year, month, *, status='sent', vat_rate=0, only_keys=None):
    """Create the invoices from the plan. Returns the created Invoice objects."""
    p = plan(year, month, vat_rate)
    start, end = month_bounds(year, month)
    created = []
    for g in p['groups']:
        if only_keys is not None and g['key'] not in only_keys:
            continue
        site = g['_site']
        title = f"Monthly services — {start.strftime('%B %Y')}" + (f" — {site.name}" if site else '')
        inv = Invoice.objects.create(
            invoice_number=_next_invoice_number(start), company=g['_company'],
            invoice_type='subscription', billing_period_start=start, billing_period_end=end,
            due_date=date.fromisoformat(g['due_date']), subtotal=_money(g['subtotal']), tax_rate=_money(g['vat_rate']),
            tax_amount=_money(g['tax_amount']), total_amount=_money(g['total']),
            wholesale_cost=_money(g['cost']), ticket_count=0, hours_worked=0,
            description=title[:500] if g['_company'] else f"{title} — {g['client_name']}"[:500],
            bill_to_name='' if g['_company'] else g['client_name'],
            status=status, sent_at=timezone.now() if status == 'sent' else None,
        )
        for l in g['lines']:
            InvoiceItem.objects.create(
                invoice=inv, description=l['description'], quantity=Decimal(str(l['quantity'])),
                unit_price=Decimal(str(l['unit_price'])), amount=Decimal(str(l['amount'])), item_type='service',
                service_type=l['service_type'], site_name=l['site_name'], unit_cost=Decimal(str(l['unit_cost'])),
                subscription_id=l['subscription_id'],
            )
        inv._recipients = g['recipients']
        inv._client_name = g['client_name']
        created.append(inv)
    return created

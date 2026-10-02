"""Per-line cost detail of an invoice (price, cost, profit per line and where each cost comes from). Internal only."""
from decimal import Decimal

from . import billing

ZERO = Decimal('0')


def money(v):
    return 'R' + f"{float(v or 0):,.2f}"


def invoice_link(inv):
    return f"/portal/invoices/?search={inv.invoice_number}"


def line_source(inv, it, cost):
    """Plain-English source for a cost line."""
    label = billing.SERVICE_LABELS.get(it['service_type'], 'Service')
    if it['service_type'] == 'wifi':
        axxess = it.get('axxess_id') or ''
        return f"Axxess wholesale {money(cost)} — WiFi registry line {axxess}" if axxess else f"Axxess wholesale {money(cost)} — WiFi line"
    if inv.invoice_type in ('adhoc', 'callout'):
        return f"Job cost {money(cost)} — {it['description']}"
    return f"{label} cost {money(cost)} — service {label}"


def lines(inv):
    """The priced lines of an invoice with cost and profit per line (full invoice, before scaling)."""
    out = []
    items = list(inv.items.all())
    if items:
        for it in items:
            qty, price, ucost = it.quantity or ZERO, it.unit_price or ZERO, it.unit_cost or ZERO
            sub = getattr(it, 'subscription', None) if it.subscription_id else None
            out.append({
                'description': it.description, 'site_name': it.site_name or '', 'service_type': it.service_type or '',
                'quantity': qty, 'unit_price': price, 'amount': it.amount if it.amount is not None else qty * price,
                'unit_cost': ucost, 'cost': qty * ucost, 'axxess_id': getattr(sub, 'axxess_id', '') if sub else '',
            })
    else:
        stype = {'wifi': 'wifi', 'sla': 'sla', 'callout': 'sla'}.get(inv.invoice_type, '')
        cost = (inv.wholesale_cost or ZERO) if inv.invoice_type in ('wifi', 'subscription') else ZERO
        axxess = inv.wifi_subscriber.axxess_id if inv.wifi_subscriber_id and inv.wifi_subscriber else ''
        out.append({
            'description': inv.description or inv.get_invoice_type_display(), 'site_name': '', 'service_type': stype,
            'quantity': Decimal('1'), 'unit_price': inv.subtotal, 'amount': inv.subtotal, 'unit_cost': cost, 'cost': cost,
            'axxess_id': axxess,
        })
    for ln in out:
        ln['profit'] = ln['amount'] - ln['cost']
    return out

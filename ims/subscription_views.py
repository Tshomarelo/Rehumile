"""
API for client branches, recurring services (subscriptions) and the combined monthly billing run.

  /sites/                  branches of a client company (billing mode per branch)
  /subscriptions/          recurring services: WiFi, email, hosting, SLA, other
  /billing/preview/        what the next run would create (changes nothing)
  /billing/run/            create the combined invoices (one per paying client)
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings as django_settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import billing
from .models import Company, ClientSite, Subscription

ROLES = ('admin', 'finance')
SERVICE_TYPES = ('wifi', 'email', 'hosting', 'sla', 'other')
LEGACY_EDITABLE = {'site', 'description', 'quantity', 'notes'}


def _denied():
    return Response({'detail': 'Admin or Finance access required.'}, status=status.HTTP_403_FORBIDDEN)


def _dec(d, field, default=None, minimum=0, strictly_above=False):
    raw = d.get(field, default)
    if raw in (None, ''):
        raise ValueError(f'{field.replace("_", " ")} is required.')
    try:
        v = Decimal(str(raw))
    except InvalidOperation:
        raise ValueError(f'{field.replace("_", " ")} must be a number.')
    if (strictly_above and v <= minimum) or (not strictly_above and v < minimum):
        raise ValueError(f'{field.replace("_", " ")} must be {"greater than" if strictly_above else "at least"} {minimum}.')
    return v


def _uuid_or_none(model, pk):
    if not pk:
        return None
    try:
        return model.objects.filter(pk=pk).first()
    except (ValueError, DjangoValidationError):
        return None


# ── Branches ─────────────────────────────────────────────────────────────────

def _site_dict(s):
    return {
        'id': str(s.id), 'company': str(s.company_id), 'company_name': s.company.name, 'name': s.name, 'address': s.address,
        'contact_name': s.contact_name, 'contact_email': s.contact_email, 'contact_phone': s.contact_phone,
        'billing_mode': s.billing_mode, 'is_active': s.is_active, 'notes': s.notes,
        'service_count': s.subscriptions.filter(status='active').count(),
        'monthly_total': float(sum((x.monthly_total for x in s.subscriptions.filter(status='active')), Decimal('0'))),
    }


def _apply_site(site, d):
    for f in ('name', 'address', 'contact_name', 'contact_email', 'contact_phone', 'notes'):
        if f in d:
            setattr(site, f, (d[f] or '').strip() if isinstance(d[f], str) else d[f])
    if 'billing_mode' in d:
        if d['billing_mode'] not in ('head_office', 'self'):
            raise ValueError('billing_mode must be head_office or self.')
        site.billing_mode = d['billing_mode']
    if 'is_active' in d:
        site.is_active = bool(d['is_active'])
    if not site.name:
        raise ValueError('Branch name is required.')


class SiteListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ROLES:
            return _denied()
        qs = ClientSite.objects.select_related('company')
        p = request.query_params
        if p.get('company'):
            qs = qs.filter(company_id=p['company'])
        if p.get('is_active') in ('1', 'true'):
            qs = qs.filter(is_active=True)
        if p.get('search'):
            qs = qs.filter(Q(name__icontains=p['search']) | Q(company__name__icontains=p['search']))
        return Response([_site_dict(s) for s in qs])

    def post(self, request):
        if request.user.role not in ROLES:
            return _denied()
        company = _uuid_or_none(Company, request.data.get('company'))
        if company is None:
            return Response({'detail': 'Choose the head-office company for this branch.'}, status=400)
        site = ClientSite(company=company)
        try:
            _apply_site(site, request.data)
            if ClientSite.objects.filter(company=company, name__iexact=site.name).exists():
                raise ValueError('This company already has a branch with that name.')
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        site.save()
        return Response(_site_dict(site), status=201)


class SiteDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        return ClientSite.objects.select_related('company').filter(pk=pk).first()

    def patch(self, request, pk):
        if request.user.role not in ROLES:
            return _denied()
        site = self._get(pk)
        if not site:
            return Response({'detail': 'Not found.'}, status=404)
        try:
            _apply_site(site, request.data)
            if ClientSite.objects.filter(company=site.company, name__iexact=site.name).exclude(pk=site.pk).exists():
                raise ValueError('This company already has a branch with that name.')
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        site.save()
        return Response(_site_dict(site))

    def delete(self, request, pk):
        if request.user.role not in ROLES:
            return _denied()
        site = self._get(pk)
        if not site:
            return Response({'detail': 'Not found.'}, status=404)
        if site.subscriptions.exists():
            return Response({'detail': 'This branch has services attached. Move or cancel them first, or mark the branch inactive.'}, status=400)
        site.delete()
        return Response(status=204)


# ── Subscriptions ────────────────────────────────────────────────────────────

def _sub_dict(s):
    return {
        'id': str(s.id), 'company': str(s.company_id) if s.company_id else None, 'client_name': s.client_label,
        'site': str(s.site_id) if s.site_id else None, 'site_name': s.site.name if s.site_id else '',
        'billing_mode': s.site.billing_mode if s.site_id else 'head_office',
        'service_type': s.service_type, 'service_label': s.get_service_type_display(), 'description': s.description,
        'quantity': float(s.quantity), 'unit_price': float(s.unit_price), 'unit_cost': float(s.unit_cost),
        'monthly_total': float(s.monthly_total), 'monthly_margin': float(s.monthly_total - s.monthly_cost),
        'billing_day': s.billing_day, 'start_date': s.start_date.isoformat(), 'end_date': s.end_date.isoformat() if s.end_date else None,
        'status': s.status, 'notes': s.notes, 'contact_email': s.contact_email,
        'managed_by': 'wifi' if s.legacy_wifi_id else ('sla' if s.legacy_sla_id else None),
    }


def _apply_sub(sub, d, editing_legacy=False):
    if editing_legacy:
        bad = [k for k in d if k not in LEGACY_EDITABLE and k not in ('id',)]
        if bad:
            raise ValueError('WiFi and SLA prices, status and dates are managed in the WiFi & SLA registry. '
                             'Here you can change the branch, wording, quantity and notes.')
    if 'company' in d:
        sub.company = _uuid_or_none(Company, d['company'])
        if d.get('company') and sub.company is None:
            raise ValueError('Client company not found.')
    if 'client_name' in d and not sub.company_id:
        sub.client_name = (d['client_name'] or '').strip()
    if 'contact_email' in d:
        sub.contact_email = (d['contact_email'] or '').strip()
    if 'site' in d:
        if d['site']:
            site = _uuid_or_none(ClientSite, d['site'])
            if site is None:
                raise ValueError('Branch not found.')
            sub.site = site
        else:
            sub.site = None
    if 'service_type' in d:
        if d['service_type'] not in SERVICE_TYPES:
            raise ValueError('Choose a valid service type.')
        sub.service_type = d['service_type']
    for f in ('description', 'notes', 'axxess_id'):
        if f in d:
            setattr(sub, f, (d[f] or '').strip())
    if 'quantity' in d:
        sub.quantity = _dec(d, 'quantity', strictly_above=True)
    if 'unit_price' in d:
        sub.unit_price = _dec(d, 'unit_price')
    if 'unit_cost' in d:
        sub.unit_cost = _dec(d, 'unit_cost', default=0)
    if 'billing_day' in d:
        try:
            day = int(d['billing_day'])
        except (TypeError, ValueError):
            raise ValueError('billing day must be a whole number.')
        if not 1 <= day <= 31:
            raise ValueError('billing day must be between 1 and 31.')
        sub.billing_day = day
    for f in ('start_date', 'end_date'):
        if f in d:
            try:
                setattr(sub, f, date.fromisoformat(str(d[f])[:10]) if d[f] else None)
            except ValueError:
                raise ValueError(f'{f.replace("_", " ")} must be a date.')
    if 'status' in d:
        if d['status'] not in ('active', 'suspended', 'cancelled'):
            raise ValueError('status must be active, suspended or cancelled.')
        sub.status = d['status']
    if not sub.start_date:
        sub.start_date = date.today()
    if sub.end_date and sub.end_date < sub.start_date:
        raise ValueError('End date cannot be before the start date.')
    if sub.site_id and sub.site.company_id != sub.company_id:
        raise ValueError('The branch must belong to the same client company.')
    if not sub.company_id and not sub.client_name:
        raise ValueError('Choose a client company or type a client name.')
    if sub.unit_price is None:
        raise ValueError('unit price is required.')


class SubscriptionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ROLES:
            return _denied()
        qs = Subscription.objects.select_related('company', 'site', 'legacy_wifi', 'legacy_sla')
        p = request.query_params
        if p.get('search'):
            qs = qs.filter(Q(company__name__icontains=p['search']) | Q(client_name__icontains=p['search'])
                           | Q(description__icontains=p['search']) | Q(site__name__icontains=p['search']))
        for param, field in (('company', 'company_id'), ('site', 'site_id'), ('service_type', 'service_type'), ('status', 'status')):
            if p.get(param):
                qs = qs.filter(**{field: p[param]})
        rows = [_sub_dict(s) for s in qs[:1000]]
        active = [r for r in rows if r['status'] == 'active']
        return Response({
            'results': rows, 'count': len(rows),
            'monthly_total': round(sum(r['monthly_total'] for r in active), 2),
            'monthly_margin': round(sum(r['monthly_margin'] for r in active), 2),
        })

    def post(self, request):
        if request.user.role not in ROLES:
            return _denied()
        sub = Subscription(quantity=Decimal('1'), unit_cost=Decimal('0'))
        try:
            _apply_sub(sub, request.data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        sub.save()
        return Response(_sub_dict(sub), status=201)


class SubscriptionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        return Subscription.objects.select_related('company', 'site', 'legacy_wifi', 'legacy_sla').filter(pk=pk).first()

    def get(self, request, pk):
        if request.user.role not in ROLES:
            return _denied()
        s = self._get(pk)
        return Response(_sub_dict(s)) if s else Response({'detail': 'Not found.'}, status=404)

    def patch(self, request, pk):
        if request.user.role not in ROLES:
            return _denied()
        sub = self._get(pk)
        if not sub:
            return Response({'detail': 'Not found.'}, status=404)
        try:
            _apply_sub(sub, request.data, editing_legacy=sub.is_managed_by_legacy)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        sub.save()
        return Response(_sub_dict(sub))

    def delete(self, request, pk):
        if request.user.role not in ROLES:
            return _denied()
        sub = self._get(pk)
        if not sub:
            return Response({'detail': 'Not found.'}, status=404)
        if sub.is_managed_by_legacy:
            return Response({'detail': 'This service comes from the WiFi & SLA registry — remove it there.'}, status=400)
        if sub.invoice_items.exists():
            return Response({'detail': 'This service has been invoiced. Set it to Cancelled instead of deleting it, so history is kept.'}, status=400)
        sub.delete()
        return Response(status=204)


# ── Billing run ──────────────────────────────────────────────────────────────

def _period(d):
    try:
        year, month = int(d.get('year') or date.today().year), int(d.get('month') or date.today().month)
        if not (1 <= month <= 12 and 2000 <= year <= 2100):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('Choose a valid year and month.')
    return year, month


def _vat(d):
    try:
        v = Decimal(str(d.get('vat_rate') or 0))
    except InvalidOperation:
        raise ValueError('VAT rate must be a number.')
    if not (0 <= v <= 100):
        raise ValueError('VAT rate must be between 0 and 100.')
    return v


class BillingPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in ROLES:
            return _denied()
        try:
            year, month = _period(request.data)
            vat = _vat(request.data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        return Response(billing.public(billing.plan(year, month, vat)))


class BillingRunView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in ROLES:
            return _denied()
        d = request.data
        try:
            year, month = _period(d)
            vat = _vat(d)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        new_status = d.get('status', 'sent')
        if new_status not in ('draft', 'sent'):
            return Response({'detail': 'status must be draft or sent.'}, status=400)
        keys = d.get('keys')
        if keys is not None and not isinstance(keys, list):
            return Response({'detail': 'keys must be a list.'}, status=400)
        invoices = billing.generate(year, month, status=new_status, vat_rate=vat, only_keys=set(keys) if keys is not None else None)
        emailed = 0
        if d.get('send_email', True) and new_status == 'sent':
            base = f"{request.scheme}://{request.get_host()}"
            for inv in invoices:
                if inv._recipients and send_invoice_email(inv, inv._recipients, base):
                    emailed += 1
        skipped = len(billing.plan(year, month, vat)['skipped'])
        return Response({
            'detail': f"Created {len(invoices)} invoice(s)" + (f", emailed {emailed}" if emailed else '') + (f". {skipped} service(s) were already invoiced." if skipped else '.'),
            'created': len(invoices), 'emailed': emailed, 'skipped': skipped,
            'invoices': [{'id': str(i.id), 'invoice_number': i.invoice_number, 'client': i._client_name,
                          'total': float(i.total_amount), 'lines': i.items.count(), 'recipients': i._recipients} for i in invoices],
        })


def send_invoice_email(invoice, recipients, base_url):
    """One email per invoice: a line per service, grouped by branch, and the single total."""
    from html import escape
    from django.core.mail import EmailMultiAlternatives
    items = list(invoice.items.all())
    groups = {}
    for it in items:
        groups.setdefault(it.site_name, []).append(it)
    rows = []
    for site, lines in groups.items():
        if site or len(groups) > 1:
            rows.append(f'<tr><td colspan="2" style="padding:10px 0 4px;font-weight:700;color:#50181E">{escape(site or "Head office")}</td></tr>')
        for it in lines:
            rows.append(f'<tr><td style="padding:4px 0;color:#444">{escape(it.description)}'
                        + (f' × {float(it.quantity):g}' if it.quantity != 1 else '')
                        + f'</td><td align="right" style="padding:4px 0">R {float(it.amount):,.2f}</td></tr>')
    due = invoice.due_date.strftime('%d %B %Y') if invoice.due_date else 'upon receipt'
    name = escape(invoice.company.name if invoice.company_id else invoice.bill_to_name)
    link = f"{base_url}/portal/client/billing/"
    html = (f'<div style="font-family:Segoe UI,Arial,sans-serif;max-width:560px;margin:auto"><h2 style="color:#50181E">Invoice {escape(invoice.invoice_number)}</h2>'
            f'<p>{name} — {escape(invoice.description)}</p><table width="100%" cellspacing="0" style="font-size:14px;border-top:2px solid #50181E">{"".join(rows)}'
            f'<tr><td style="padding:10px 0;border-top:1px solid #ccc;font-weight:700">Total due</td>'
            f'<td align="right" style="padding:10px 0;border-top:1px solid #ccc;font-weight:700;color:#50181E">R {float(invoice.total_amount):,.2f}</td></tr></table>'
            f'<p>Payment is due by <b>{due}</b>. <a href="{link}">View or pay online</a>.</p>'
            f'<p style="color:#888;font-size:12px">Rehumile TMW</p></div>')
    plain = (f"Invoice {invoice.invoice_number} — {invoice.description}\n"
             + "\n".join(f"  {it.site_name + ': ' if it.site_name else ''}{it.description}  R {float(it.amount):,.2f}" for it in items)
             + f"\n\nTotal due: R {float(invoice.total_amount):,.2f}\nDue by: {due}\n{link}")
    try:
        msg = EmailMultiAlternatives(f"Invoice {invoice.invoice_number} — Rehumile TMW", plain, django_settings.DEFAULT_FROM_EMAIL, recipients)
        msg.attach_alternative(html, 'text/html')
        msg.send()
        return True
    except Exception:
        return False

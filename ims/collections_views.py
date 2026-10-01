"""
API for: recurring expenses, collections (unpaid invoices), recording payments, reminders,
and the client-facing invoice page (/invoice/<token>/).
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import collections as coll, housekeeping
from . import recurring
from .ledger import ensure_seeded
from .models import ExpenseCategory, Invoice, Notification, RecurringExpense, User

ROLES = ('admin', 'finance')
PAY_ROLES = ('admin', 'finance', 'cashier')


def _denied():
    return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)


def _base(request):
    return f"{request.scheme}://{request.get_host()}"


# ── Recurring expenses ───────────────────────────────────────────────────────

def _rec_dict(t, today=None):
    return {
        'id': str(t.id), 'name': t.name, 'vendor': t.vendor, 'expense_category': str(t.expense_category_id),
        'category_name': t.expense_category.name, 'amount': float(t.amount), 'description': t.description,
        'frequency': t.frequency, 'frequency_label': t.get_frequency_display(), 'day_of_month': t.day_of_month,
        'start_date': t.start_date.isoformat(), 'end_date': t.end_date.isoformat() if t.end_date else None,
        'payment_status': t.payment_status, 'is_active': t.is_active,
        'last_posted_for': t.last_posted_for.isoformat() if t.last_posted_for else None,
        'next_due': t.next_due(today).isoformat() if t.next_due(today) else None,
        'posted_count': t.expenses.count(),
    }


def _apply_rec(t, d):
    for f in ('name', 'vendor', 'description'):
        if f in d:
            setattr(t, f, (d[f] or '').strip())
    if 'expense_category' in d:
        try:
            t.expense_category = ExpenseCategory.objects.get(pk=d['expense_category'], is_active=True)
        except (ExpenseCategory.DoesNotExist, ValueError, DjangoValidationError):
            raise ValueError('Expense category not found.')
    if 'amount' in d:
        try:
            t.amount = Decimal(str(d['amount']))
        except InvalidOperation:
            raise ValueError('Amount must be a number.')
        if t.amount <= 0:
            raise ValueError('Amount must be greater than zero.')
    if 'frequency' in d:
        if d['frequency'] not in ('monthly', 'quarterly', 'annual'):
            raise ValueError('Frequency must be monthly, quarterly or yearly.')
        t.frequency = d['frequency']
    if 'day_of_month' in d:
        try:
            t.day_of_month = int(d['day_of_month'])
        except (TypeError, ValueError):
            raise ValueError('Day of month must be a whole number.')
        if not 1 <= t.day_of_month <= 31:
            raise ValueError('Day of month must be between 1 and 31.')
    for f in ('start_date', 'end_date'):
        if f in d:
            try:
                setattr(t, f, date.fromisoformat(str(d[f])[:10]) if d[f] else None)
            except ValueError:
                raise ValueError(f'{f.replace("_", " ").capitalize()} must be a date.')
    if 'payment_status' in d:
        if d['payment_status'] not in ('paid', 'unpaid'):
            raise ValueError('Payment status must be paid or unpaid.')
        t.payment_status = d['payment_status']
    if 'is_active' in d:
        t.is_active = bool(d['is_active'])
    for f, label in (('name', 'Name'), ('vendor', 'Vendor / supplier')):
        if not getattr(t, f):
            raise ValueError(f'{label} is required.')
    if not t.expense_category_id:
        raise ValueError('Choose an expense category.')
    if not t.start_date:
        raise ValueError('Start date is required.')
    if t.end_date and t.end_date < t.start_date:
        raise ValueError('End date cannot be before the start date.')


class RecurringExpenseListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ROLES:
            return _denied()
        rows = [_rec_dict(t) for t in RecurringExpense.objects.select_related('expense_category')]
        active = [r for r in rows if r['is_active']]
        monthly = sum(r['amount'] * {'monthly': 1, 'quarterly': 1 / 3, 'annual': 1 / 12}[r['frequency']] for r in active)
        return Response({'results': rows, 'count': len(rows), 'monthly_equivalent': round(monthly, 2)})

    def post(self, request):
        if request.user.role not in ROLES:
            return _denied()
        ensure_seeded()
        t = RecurringExpense(created_by=request.user)
        try:
            _apply_rec(t, request.data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        t.save()
        return Response(_rec_dict(t), status=201)


class RecurringExpenseDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        return RecurringExpense.objects.select_related('expense_category').filter(pk=pk).first()

    def patch(self, request, pk):
        if request.user.role not in ROLES:
            return _denied()
        t = self._get(pk)
        if not t:
            return Response({'detail': 'Not found.'}, status=404)
        try:
            _apply_rec(t, request.data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        t.save()
        return Response(_rec_dict(t))

    def delete(self, request, pk):
        if request.user.role not in ROLES:
            return _denied()
        t = self._get(pk)
        if not t:
            return Response({'detail': 'Not found.'}, status=404)
        if t.expenses.exists():
            t.is_active = False       # keep the history of what it posted
            t.save(update_fields=['is_active', 'updated_at'])
            return Response({'detail': 'It has already posted expenses, so it was paused instead of deleted.', 'paused': True})
        t.delete()
        return Response(status=204)


class RecurringExpenseRunView(APIView):
    """Post everything that is due now (the daily job does this automatically)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in ROLES:
            return _denied()
        made = recurring.post_due(user=request.user)
        return Response({'posted': len(made), 'items': [{'vendor': e.vendor, 'date': e.expense_date.isoformat(), 'amount': float(e.amount)} for e in made]})


# ── Collections ──────────────────────────────────────────────────────────────

class CollectionsView(APIView):
    """Every invoice still owed, most overdue first."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ROLES:
            return _denied()
        housekeeping.run_if_due(request.user)
        coll.mark_overdue()                      # cheap; keeps the list honest even if the daily job has not run
        today = coll._today()
        qs = Invoice.objects.filter(status__in=('sent', 'partially_paid', 'overdue')).select_related('company', 'wifi_subscriber', 'sla_contract')
        rows = []
        for inv in qs:
            late = coll.days_overdue(inv, today)
            rows.append({
                'id': str(inv.id), 'invoice_number': inv.invoice_number, 'client': coll.client_name(inv) or '—',
                'description': inv.description, 'total': float(inv.balance_due), 'invoice_total': float(inv.total_amount), 'amount_paid': float(inv.amount_paid or 0),
                'due_date': inv.due_date.isoformat() if inv.due_date else None, 'days_overdue': late, 'status': inv.status,
                'emails': coll.recipients_for(inv), 'phone': coll.phone_for(inv),
                'reminder_count': inv.reminder_count, 'last_reminder_at': inv.last_reminder_at.isoformat() if inv.last_reminder_at else None,
                'paid_notice': inv.payment_notice_at.isoformat() if inv.payment_notice_at else None, 'paid_notice_note': inv.payment_notice_note,
                'public_url': f"{_base(request)}/invoice/{inv.ensure_public_token()}/",
                'consider_suspending': late >= coll.SUSPEND_AFTER_DAYS,
            })
        rows.sort(key=lambda r: (-r['days_overdue'], r['due_date'] or ''))
        od = [r for r in rows if r['days_overdue'] > 0]
        return Response({
            'results': rows, 'count': len(rows), 'total_owed': round(sum(r['total'] for r in rows), 2),
            'overdue_count': len(od), 'overdue_total': round(sum(r['total'] for r in od), 2),
            'suspend_after_days': coll.SUSPEND_AFTER_DAYS, 'max_reminders': coll.MAX_REMINDERS,
        })


class RecordPaymentView(APIView):
    """POST {amount?, paid_on?, method: eft|cash|card|payfast|other, reference?, note?} — a full payment, or a part payment when amount is less than the balance."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in PAY_ROLES:
            return _denied()
        inv = Invoice.objects.select_related('company').filter(pk=pk).first()
        if not inv:
            return Response({'detail': 'Invoice not found.'}, status=404)
        d = request.data
        try:
            raw = d.get('paid_on') or d.get('payment_date')
            paid_on = date.fromisoformat(str(raw)[:10]) if raw else None
            method = d.get('method') or d.get('payment_method') or 'eft'
            reference = (d.get('reference') or '').strip()[:100]
            note = (d.get('note') or d.get('notes') or '').strip()[:200]
            coll.record_payment(inv, request.user, paid_on, method, reference, note, amount=d.get('amount'))
        except (ValueError, InvalidOperation) as exc:
            return Response({'detail': str(exc) if isinstance(exc, ValueError) else 'Amount must be a number.'}, status=400)
        paid = paid_on or coll._today()
        warning = ''
        if inv.billing_period_end and (paid.year, paid.month) > (inv.billing_period_end.year, inv.billing_period_end.month):
            warning = (f"This payment is dated {paid:%d %b %Y}, a later month than the work it pays for ({inv.billing_period_end:%B %Y}). "
                       f"It will count as money received in {paid:%B %Y}. If the money really arrived earlier, change the payment date.")
        return Response({'id': str(inv.id), 'status': inv.status, 'payment_date': inv.payment_date.isoformat() if inv.payment_date else None,
                         'amount_paid': float(inv.amount_paid), 'balance_due': float(inv.balance_due), 'warning': warning}, status=201)


class InvoiceReminderView(APIView):
    """Send one payment reminder now (also usable before an invoice is overdue)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id):
        if request.user.role not in ROLES + ('agent',):
            return _denied()
        inv = Invoice.objects.select_related('company', 'wifi_subscriber', 'sla_contract').filter(pk=invoice_id).first()
        if not inv:
            return Response({'detail': 'Invoice not found.'}, status=404)
        if inv.status not in ('sent', 'partially_paid', 'overdue'):
            return Response({'detail': f'Only unpaid invoices can be chased (this one is {inv.status}).'}, status=400)
        if not coll.recipients_for(inv):
            return Response({'detail': 'There is no email address on file for this client. Add one on the subscription or company.'}, status=400)
        ok = coll.send_reminder(inv, _base(request), overdue=inv.status == 'overdue' or coll.days_overdue(inv) > 0)
        return Response({'detail': 'Reminder sent.' if ok else 'The email could not be sent.', 'sent': ok}, status=200 if ok else 502)


class InvoiceSendView(APIView):
    """POST — email an existing invoice to the client. A draft is issued (status Sent, booked in the ledger) when it goes out."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ROLES:
            return _denied()
        inv = Invoice.objects.select_related('company', 'wifi_subscriber', 'sla_contract').filter(pk=pk).first()
        if not inv:
            return Response({'detail': 'Invoice not found.'}, status=404)
        if inv.status in ('paid', 'cancelled'):
            return Response({'detail': f'This invoice is {inv.status}; there is nothing to send.'}, status=400)
        to = coll.recipients_for(inv)
        if request.data.get('email'):
            to = [str(request.data['email']).strip()]
        if not to:
            return Response({'detail': 'There is no email address on file for this client. Add one on the company or service, or type one here.'}, status=400)
        from .subscription_views import send_invoice_email
        issued = False
        if inv.status == 'draft':
            from django.utils import timezone as _tz
            from .ledger import post_invoice_sent
            inv.status = 'sent'
            inv.sent_at = _tz.now()
            inv.save()
            post_invoice_sent(inv, request.user)
            issued = True
        ok = send_invoice_email(inv, to, _base(request))
        if not ok:
            return Response({'detail': 'The email could not be sent.' + (' The invoice was issued though.' if issued else ''), 'sent': False, 'status': inv.status}, status=502)
        return Response({'detail': f"Invoice {inv.invoice_number} sent to {', '.join(to)}." + (' It is now issued.' if issued else ''),
                         'sent': True, 'status': inv.status, 'issued': issued})


# ── Client-facing invoice page ───────────────────────────────────────────────

class PublicMixin:
    authentication_classes = []
    permission_classes = []
    throttle_classes = [ScopedRateThrottle]


def _public_invoice(token):
    if not token or len(token) < 20:
        return None
    return (Invoice.objects.select_related('company', 'wifi_subscriber').exclude(status__in=('draft', 'cancelled'))
            .filter(public_token=token).first())


class PublicInvoiceView(PublicMixin, APIView):
    throttle_scope = 'invoice_public'

    def get(self, request, token):
        from django.conf import settings
        from .views import _company_settings
        inv = _public_invoice(token)
        if not inv:
            return Response({'detail': 'This invoice link is not valid.'}, status=404)
        cs = _company_settings()
        late = coll.days_overdue(inv) if inv.status in ('sent', 'partially_paid', 'overdue') else 0
        return Response({
            'invoice_number': inv.invoice_number, 'client_name': coll.client_name(inv), 'description': inv.description,
            'status': 'overdue' if (inv.status == 'sent' and late) else inv.status,
            'issue_date': (inv.sent_at.date() if inv.sent_at else inv.created_at.date()).isoformat(),
            'due_date': inv.due_date.isoformat() if inv.due_date else None, 'days_overdue': late,
            'paid_on': inv.payment_date.isoformat() if inv.payment_date else None,
            'period': {'start': inv.billing_period_start.isoformat(), 'end': inv.billing_period_end.isoformat()},
            'items': [{'description': i.description, 'site_name': i.site_name, 'quantity': float(i.quantity),
                       'unit_price': float(i.unit_price), 'amount': float(i.amount)} for i in inv.items.all()],
            'subtotal': float(inv.subtotal), 'tax_rate': float(inv.tax_rate), 'tax_amount': float(inv.tax_amount), 'total_amount': float(inv.total_amount),
            'reference': inv.invoice_number,
            'bank': {'account_name': cs.account_name, 'bank_name': cs.bank_name, 'account_number': cs.account_number,
                     'branch_code': cs.branch_code, 'swift_code': cs.swift_code},
            'terms': cs.payment_terms,
            'company': {'name': cs.company_name, 'phone': cs.phone, 'email': cs.email, 'vat_number': cs.vat_number},
            'card_payments': bool(getattr(settings, 'PAYFAST_MERCHANT_ID', '')),
            'paid_notice': bool(inv.payment_notice_at),
        })


class PublicInvoiceNoticeView(PublicMixin, APIView):
    """'I have paid' — tells the team to check the bank; it does NOT mark the invoice paid."""
    throttle_scope = 'invoice_notice'

    def post(self, request, token):
        inv = _public_invoice(token)
        if not inv:
            return Response({'detail': 'This invoice link is not valid.'}, status=404)
        if inv.status == 'paid':
            return Response({'detail': 'This invoice is already marked as paid. Thank you!'}, status=409)
        note = str(request.data.get('note') or '').strip()[:400]
        Invoice.objects.filter(pk=inv.pk).update(payment_notice_at=timezone.now(), payment_notice_note=note)
        who = coll.client_name(inv)
        for u in User.objects.filter(role__in=ROLES, is_active=True):
            Notification.objects.create(user=u, notification_type='invoice', title=f"{who} says invoice {inv.invoice_number} is paid",
                                        message=f"{who} used \"I have paid\" for R{inv.total_amount:,.2f}." + (f" Note: {note}" if note else '') + " Check the bank, then record the payment.",
                                        invoice=inv, metadata={'url': '/portal/dashboard/subscriptions/#collections'})
        return Response({'detail': 'Thank you — we will check our bank account and confirm shortly.'})

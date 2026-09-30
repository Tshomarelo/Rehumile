"""
Collecting money from clients: recording payments, overdue status and reminders.

Clients pay by EFT, so the flow is: invoice goes out with the bank details and the invoice
number as the payment reference -> money arrives -> staff record it ("Record payment") ->
anything unpaid past its due date becomes overdue and gets polite reminders.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from .models import CashTransaction, Invoice

REMINDER_GAP_DAYS = 7
MAX_REMINDERS = 3
SUSPEND_AFTER_DAYS = 14


def _today():
    from . import billing
    return billing._today()


def days_overdue(inv, today=None):
    today = today or _today()
    return max((today - inv.due_date).days, 0) if inv.due_date else 0


def recipients_for(inv):
    """Email addresses to write to: company billing contact, else the subscription contact, else the branch."""
    emails = []
    if inv.company_id:
        emails += [inv.company.billing_email, inv.company.contact_email]
    for it in inv.items.select_related('subscription__site'):
        sub = it.subscription
        if sub is not None:
            emails += [sub.contact_email, sub.site.contact_email if sub.site_id else '']
    if inv.wifi_subscriber_id:
        emails.append(inv.wifi_subscriber.contact_email)
    if inv.sla_contract_id:
        emails.append(inv.sla_contract.contact_email)
    seen, out = set(), []
    for e in emails:
        if e and e.lower() not in seen:
            seen.add(e.lower())
            out.append(e)
    return out[:2]


def phone_for(inv):
    for it in inv.items.select_related('subscription'):
        if it.subscription is not None and it.subscription.contact_phone:
            return it.subscription.contact_phone
    if inv.wifi_subscriber_id and inv.wifi_subscriber.contact_phone:
        return inv.wifi_subscriber.contact_phone
    if inv.company_id and inv.company.contact_phone:
        return inv.company.contact_phone
    return ''


def client_name(inv):
    return inv.company.name if inv.company_id else (inv.bill_to_name or (inv.wifi_subscriber.client_name if inv.wifi_subscriber_id else ''))


@transaction.atomic
def record_payment(inv, user, paid_on=None, method='eft', reference='', note='', amount=None):
    """
    Record money received for an invoice — the one payment path used by the UI, the API and admin.
    Creates an InvoicePayment (full or part), a cash record and the ledger entries, then updates the
    invoice's amount_paid and status (Partially Paid until the balance reaches zero, then Paid).
    """
    from .ledger import post_invoice_payment
    from .models import InvoicePayment
    if inv.status in ('paid', 'cancelled'):
        raise ValueError(f'This invoice is already {inv.status}.')
    method = (method or 'eft').lower()
    if method not in ('eft', 'cash', 'card', 'payfast', 'other'):
        raise ValueError('Payment method must be EFT, cash, card, PayFast or other.')
    paid_on = paid_on or _today()
    if paid_on > _today():
        raise ValueError('The payment date cannot be in the future.')
    balance = inv.balance_due
    amount = Decimal(str(amount)) if amount not in (None, '') else balance
    if amount <= 0:
        raise ValueError('The amount must be greater than zero.')
    if amount > balance:
        raise ValueError(f'The amount is more than the outstanding balance (R {balance:,.2f}).')
    note_text = (f"Paid {paid_on:%d %b %Y} by {method.upper()}" + (f" — ref {reference}" if reference else '') + (f" — {note}" if note else ''))
    payment = InvoicePayment.objects.create(
        invoice=inv, amount=amount, payment_date=paid_on, payment_method=method,
        notes=(reference + (' — ' if reference and note else '') + note)[:255], recorded_by=user if getattr(user, 'is_authenticated', False) else None)
    inv.amount_paid = (inv.amount_paid or 0) + amount
    if inv.amount_paid >= inv.total_amount:
        inv.status, inv.payment_date = 'paid', paid_on
    else:
        inv.status = 'partially_paid'
    if reference or note:
        inv.notes = (inv.notes + '\n' if inv.notes else '') + note_text
    inv.save()
    CashTransaction.objects.create(
        invoice=inv, amount=amount, payment_method=method if method in ('eft', 'cash', 'card') else 'eft', cash_flow_stream='ocf',
        transaction_category='sale',
        description=f"Payment {inv.invoice_number} ({method.upper()})" + (f" ref {reference}" if reference else ''), performed_by=user)
    post_invoice_payment(payment, user)
    return inv


def _bank_block(cs):
    rows = [(k, v) for k, v in (('Account name', cs.account_name), ('Bank', cs.bank_name), ('Account number', cs.account_number),
                                 ('Branch code', cs.branch_code)) if v]
    return rows


def send_reminder(inv, base_url, *, overdue=True):
    """One friendly reminder email with the invoice link and bank details. Returns True if an email was sent."""
    from html import escape
    from .views import _company_settings
    to = recipients_for(inv)
    if not to:
        return False
    cs = _company_settings()
    token = inv.ensure_public_token()
    link = f"{base_url}/invoice/{token}/"
    due = inv.due_date.strftime('%d %B %Y') if inv.due_date else 'now'
    late = days_overdue(inv)
    lead = (f"This is a friendly reminder that invoice {inv.invoice_number} was due on {due}"
            + (f" ({late} day{'s' if late != 1 else ''} ago)" if late else '') + ' and we have not yet received payment.') if overdue else \
        f"Invoice {inv.invoice_number} is due on {due}."
    bank = _bank_block(cs)
    text = (f"Hi {client_name(inv)},\n\n{lead}\n\nAmount: R {float(inv.total_amount):,.2f}\nPayment reference: {inv.invoice_number}\n"
            + ''.join(f"{k}: {v}\n" for k, v in bank) + f"\nView your invoice: {link}\n\nIf you have already paid, please reply or use "
            f"\"I have paid\" on the invoice page and we will match it. Thank you!\n{cs.company_name}")
    html = (f'<div style="font-family:Segoe UI,Arial,sans-serif;max-width:560px;margin:auto"><h2 style="color:#50181E">Payment reminder</h2>'
            f'<p>Hi {escape(client_name(inv))},</p><p>{escape(lead)}</p>'
            f'<p style="font-size:18px"><b>R {float(inv.total_amount):,.2f}</b> — reference <b>{escape(inv.invoice_number)}</b></p>'
            + ('<table cellspacing="0" style="font-size:14px;background:#fdf5f5;padding:8px 12px;border-left:4px solid #50181E">' + ''.join(f'<tr><td style="color:#777;padding:2px 14px 2px 0">{escape(k)}</td><td><b>{escape(v)}</b></td></tr>' for k, v in bank) + '</table>' if bank else '')
            + f'<p><a href="{link}" style="display:inline-block;background:#50181E;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none">View invoice</a></p>'
            f'<p style="color:#888;font-size:12px">Already paid? Use "I have paid" on the invoice page, or reply to this email.<br>{escape(cs.company_name)}</p></div>')
    try:
        msg = EmailMultiAlternatives(f"{'Payment reminder — ' if overdue else ''}Invoice {inv.invoice_number}", text, django_settings.DEFAULT_FROM_EMAIL, to)
        msg.attach_alternative(html, 'text/html')
        msg.send()
    except Exception:
        return False
    Invoice.objects.filter(pk=inv.pk).update(reminder_count=inv.reminder_count + 1, last_reminder_at=timezone.now())
    return True


def mark_overdue(today=None):
    """Sent invoices whose due date has passed become Overdue. Returns how many changed."""
    today = today or _today()
    n = 0
    for inv in Invoice.objects.filter(status__in=('sent', 'partially_paid'), due_date__lt=today):
        Invoice.objects.filter(pk=inv.pk).update(status='overdue', updated_at=timezone.now())
        n += 1
    return n


def send_due_reminders(base_url, today=None, send=True):
    """Overdue invoices: a reminder the day after the due date, then weekly, at most MAX_REMINDERS times."""
    today = today or _today()
    sent = 0
    for inv in Invoice.objects.select_related('company', 'wifi_subscriber', 'sla_contract').filter(status='overdue', due_date__lt=today, reminder_count__lt=MAX_REMINDERS):
        if inv.last_reminder_at and (timezone.now() - inv.last_reminder_at) < timedelta(days=REMINDER_GAP_DAYS):
            continue
        if inv.payment_notice_at:
            continue                                   # the client says they have paid — staff should check the bank first
        if send and send_reminder(inv, base_url):
            sent += 1
    return sent

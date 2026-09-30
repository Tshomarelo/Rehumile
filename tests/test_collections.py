from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command
from django.db.models import Sum
from django.test import Client
from django.utils import timezone

from ims import billing, collections as coll, finance, recurring
from ims.ledger import ensure_seeded
from ims.models import (
    CashTransaction, Company, Expense, ExpenseCategory, Invoice, LedgerEntry, Notification,
    RecurringExpense, Subscription, WifiSubscriber,
)
from tests.conftest import client_for, make_user


def category(name='Software & Subscriptions'):
    ensure_seeded()
    return ExpenseCategory.objects.get(name=name)


def template(**kw):
    kw.setdefault('name', 'Office Axxess fibre'); kw.setdefault('vendor', 'Axxess'); kw.setdefault('amount', 899)
    kw.setdefault('expense_category', category('Internet & Axxess (own lines)')); kw.setdefault('start_date', date(2026, 7, 1))
    return RecurringExpense.objects.create(**kw)


# ── recurring expenses ───────────────────────────────────────────────────────

def test_monthly_occurrences_catch_up_and_day_clamp(db):
    t = template(day_of_month=31, start_date=date(2026, 1, 15))
    days = t.occurrences(date(2026, 4, 30))
    assert days == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]   # short months use the last day
    assert template(name='x', day_of_month=10, start_date=date(2026, 3, 20)).occurrences(date(2026, 5, 31))[0] == date(2026, 4, 10)  # first date on/after start


def test_quarterly_annual_and_end_date(db):
    q = template(name='q', frequency='quarterly', start_date=date(2026, 1, 5), day_of_month=5)
    assert q.occurrences(date(2026, 12, 31)) == [date(2026, 1, 5), date(2026, 4, 5), date(2026, 7, 5), date(2026, 10, 5)]
    a = template(name='a', frequency='annual', start_date=date(2025, 3, 1), end_date=date(2026, 12, 31))
    assert a.occurrences(date(2030, 1, 1)) == [date(2025, 3, 1), date(2026, 3, 1)]


def test_post_due_creates_expenses_once_and_books_them(db):
    t = template()
    made = recurring.post_due(date(2026, 9, 15))
    assert [e.expense_date for e in made] == [date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]
    e = made[0]
    assert e.expense_category == t.expense_category and e.account.system_key == 'OPEX_UTILITIES' and e.category == 'operating' and e.amount == 899
    assert e.recurring_source == t and e.payment_status == 'paid'
    assert recurring.post_due(date(2026, 9, 15)) == []                                   # idempotent
    assert len(recurring.post_due(date(2026, 10, 1))) == 1                              # next month appears
    agg = LedgerEntry.objects.aggregate(d=Sum('debit'), c=Sum('credit'))
    assert agg['d'] == agg['c'] and agg['d'] == 899 * 4
    s = finance.summary(date(2026, 9, 1), date(2026, 9, 30))
    assert s['expenses']['operating'] == 899


def test_paused_and_future_templates_do_not_post(db):
    template(is_active=False); template(name='later', start_date=date(2027, 1, 1))
    assert recurring.post_due(date(2026, 9, 15)) == []


def test_unpaid_template_posts_payable(db):
    template(payment_status='unpaid')
    e = recurring.post_due(date(2026, 7, 2))[0]
    assert e.payment_status == 'unpaid'


def test_recurring_api_validation_and_rules(api, cashier):
    cat = category()
    body = {'name': 'Domain', 'vendor': 'Afrihost', 'expense_category': str(cat.id), 'amount': '180', 'frequency': 'annual', 'day_of_month': 15, 'start_date': '2026-09-15'}
    r = api.post('/api/recurring-expenses/', body, format='json')
    assert r.status_code == 201 and r.data['next_due'] == '2026-09-15' and r.data['category_name'] == cat.name
    bad = lambda **k: api.post('/api/recurring-expenses/', {**body, **k}, format='json').status_code
    assert bad(amount='0') == 400 and bad(amount='x') == 400 and bad(frequency='weekly') == 400 and bad(day_of_month=32) == 400
    assert bad(start_date='nope') == 400 and bad(end_date='2026-01-01') == 400 and bad(expense_category='bogus') == 400 and bad(vendor='') == 400
    lst = api.get('/api/recurring-expenses/').data
    assert lst['count'] == 1 and lst['monthly_equivalent'] == 15.0                         # R180 a year = R15 a month
    assert client_for(cashier).get('/api/recurring-expenses/').status_code == 403
    run = api.post('/api/recurring-expenses/run/', {'today': '2030-01-01'}, format='json')
    assert run.status_code == 200 and run.data['posted'] == 1
    assert api.get('/api/recurring-expenses/run/').status_code == 405
    # once it has posted, deleting only pauses it
    d = api.delete(f"/api/recurring-expenses/{r.data['id']}/")
    assert d.status_code == 200 and d.data['paused'] and RecurringExpense.objects.get(pk=r.data['id']).is_active is False
    assert api.patch(f"/api/recurring-expenses/{r.data['id']}/", {'amount': '200', 'is_active': True}, format='json').data['amount'] == 200


def test_posted_expense_shows_in_expense_list_and_cannot_duplicate(api, db):
    t = template()
    recurring.post_due(date(2026, 7, 5))
    rows = api.get('/api/expenses/').data['results']
    assert rows and rows[0]['is_recurring'] and rows[0]['vendor'] == 'Axxess'
    with pytest.raises(Exception):
        Expense.objects.create(category='operating', account=t.expense_category.account, amount=1, vendor='x', expense_date=date(2026, 7, 1),
                               recurring_source=t, occurrence_date=date(2026, 7, 1))


# ── collections ──────────────────────────────────────────────────────────────

def home(name='Thabo Home', email='thabo@mail.co', phone='0683973484', price=399, cost=250, status_day=31):
    w = WifiSubscriber.objects.create(client_name=name, retail_price=price, wholesale_cost=cost, contact_email=email, contact_phone=phone, billing_day=status_day)
    return w


@pytest.fixture
def unpaid(db, monkeypatch):
    """Two home clients invoiced for September, due 30 Sept."""
    monkeypatch.setattr(billing, '_today', lambda: date(2026, 9, 30))
    home('Thabo Home'); home('Nomsa Home', 'nomsa@mail.co', '0711112222', 599, 350)
    invs = billing.generate(2026, 9)
    Invoice.objects.update(sent_at=timezone.make_aware(datetime(2026, 9, 1, 9, 0)))     # issued on the 1st, whatever the real date is
    return [Invoice.objects.get(pk=i.pk) for i in invs]


def by_name(invs, name):
    return next(i for i in invs if i.bill_to_name == name)


def test_home_client_invoice_due_at_month_end(unpaid):
    assert len(unpaid) == 2 and {i.due_date for i in unpaid} == {date(2026, 9, 30)}
    assert all(i.bill_to_name and i.company is None and i.public_token for i in unpaid)


def test_due_date_is_never_in_the_past(db, monkeypatch):
    monkeypatch.setattr(billing, '_today', lambda: date(2026, 10, 3))
    home()
    assert billing.generate(2026, 9)[0].due_date == date(2026, 10, 10)        # run late: 7 days from today


def test_mark_overdue_and_collections_list(api, unpaid):
    assert coll.mark_overdue(date(2026, 9, 30)) == 0                            # due today is not late yet
    assert coll.mark_overdue(date(2026, 10, 3)) == 2
    assert set(Invoice.objects.values_list('status', flat=True)) == {'overdue'}
    Invoice.objects.filter(pk=unpaid[0].pk).update(due_date=billing._today() - timedelta(days=20))
    r = api.get('/api/collections/').data
    assert r['count'] == 2 and r['total_owed'] == 399 + 599
    first = r['results'][0]
    assert first['days_overdue'] >= 20 and first['consider_suspending'] and first['emails'] and first['phone'] and '/invoice/' in first['public_url']
    assert r['overdue_count'] >= 1


def test_record_payment_full_flow(api, unpaid):
    inv = by_name(unpaid, 'Thabo Home')
    r = api.post(f'/api/invoices/{inv.id}/record-payment/', {'paid_on': '2026-09-28', 'method': 'eft', 'reference': 'THABO SEP'}, format='json')
    assert r.status_code == 201 and r.data['status'] == 'paid' and r.data['balance_due'] == 0
    inv.refresh_from_db()
    assert inv.status == 'paid' and inv.payment_date == date(2026, 9, 28) and 'THABO SEP' in inv.notes
    tx = CashTransaction.objects.get(invoice=inv)
    assert tx.amount == inv.total_amount and tx.payment_method == 'eft'
    agg = LedgerEntry.objects.aggregate(d=Sum('debit'), c=Sum('credit'))
    assert agg['d'] == agg['c'] > 0
    s = finance.summary(date(2026, 9, 1), date(2026, 9, 30), today=date(2026, 9, 30))
    assert s['invoices']['paid']['subtotal'] == 399 and s['revenue']['direct_sales'] == 0            # the cash record is not counted twice
    assert s['invoices']['unpaid']['count'] == 1
    assert api.post(f'/api/invoices/{inv.id}/record-payment/', {}, format='json').status_code == 400   # already paid


def test_record_payment_validation_and_permissions(api, unpaid, cashier):
    inv = unpaid[1]
    url = f'/api/invoices/{inv.id}/record-payment/'
    assert api.post(url, {'paid_on': (billing._today() + timedelta(days=2)).isoformat()}, format='json').status_code == 400
    assert api.post(url, {'method': 'bitcoin'}, format='json').status_code == 400
    assert api.post(url, {'amount': '0'}, format='json').status_code == 400
    assert api.post(url, {'amount': '99999'}, format='json').status_code == 400                       # more than the balance
    assert api.post(url, {'amount': 'abc'}, format='json').status_code == 400
    assert client_for(make_user('client')).post(url, {}, format='json').status_code == 403
    assert client_for(cashier).post(url, {'method': 'cash'}, format='json').status_code == 201        # the till can take payments
    assert api.post('/api/invoices/00000000-0000-0000-0000-000000000000/record-payment/', {}, format='json').status_code == 404


def test_reminder_schedule_and_content(db, unpaid, monkeypatch):
    base = 'https://rehumile.test'
    coll.mark_overdue(date(2026, 10, 1))
    assert coll.send_due_reminders(base, today=date(2026, 10, 1)) == 2
    m = mail.outbox[-1]
    assert 'Payment reminder' in m.subject and 'R 399.00' in m.body or 'R 599.00' in m.body
    assert unpaid[0].invoice_number in m.body and '/invoice/' in m.body
    assert coll.send_due_reminders(base, today=date(2026, 10, 2)) == 0                               # not again for a week
    Invoice.objects.update(last_reminder_at=timezone.now() - timedelta(days=8))
    assert coll.send_due_reminders(base, today=date(2026, 10, 9)) == 2
    Invoice.objects.update(last_reminder_at=timezone.now() - timedelta(days=8))
    assert coll.send_due_reminders(base, today=date(2026, 10, 17)) == 2
    Invoice.objects.update(last_reminder_at=timezone.now() - timedelta(days=8))
    assert coll.send_due_reminders(base, today=date(2026, 10, 25)) == 0                              # stops after 3
    assert set(Invoice.objects.values_list('reminder_count', flat=True)) == {3}


def test_no_reminder_when_client_says_paid_or_no_email(db, monkeypatch):
    monkeypatch.setattr(billing, '_today', lambda: date(2026, 9, 25))
    home('A', 'a@mail.co'); home('B', '')
    a, b = sorted(billing.generate(2026, 9), key=lambda i: i.bill_to_name)
    coll.mark_overdue(date(2026, 10, 2))
    Invoice.objects.filter(pk=a.pk).update(payment_notice_at=timezone.now())
    assert coll.send_due_reminders('https://x', today=date(2026, 10, 2)) == 0


def test_reminder_endpoint(api, unpaid, db):
    inv = unpaid[0]
    r = api.post(f'/api/invoices/{inv.id}/remind/')
    assert r.status_code == 200 and mail.outbox and Invoice.objects.get(pk=inv.pk).reminder_count == 1
    assert api.post(f'/api/invoices/{inv.id}/remind/').status_code == 200
    Invoice.objects.filter(pk=inv.pk).update(status='paid')
    assert api.post(f'/api/invoices/{inv.id}/remind/').status_code == 400
    Subscription.objects.update(contact_email=''); WifiSubscriber.objects.update(contact_email='')
    assert api.post(f'/api/invoices/{unpaid[1].id}/remind/').status_code == 400
    assert client_for(make_user('finance')).post(f'/api/invoices/{unpaid[1].id}/remind/').status_code == 400   # allowed role, but no email left


# ── the client's invoice page ────────────────────────────────────────────────

def pubinv(token, path=''):
    return f'/api/public/invoices/{token}/{path}'


def test_public_invoice_shows_bank_details_and_reference(unpaid, db):
    from ims.views import _company_settings
    cs = _company_settings(); cs.account_name = 'Rehumile TMW'; cs.bank_name = 'FNB'; cs.account_number = '62000000000'; cs.branch_code = '250655'; cs.save()
    inv = by_name(unpaid, 'Thabo Home')
    d = Client().get(pubinv(inv.public_token)).json()
    assert d['reference'] == inv.invoice_number and d['bank']['account_number'] == '62000000000' and d['total_amount'] == 399
    assert d['status'] == 'sent' and d['client_name'] == 'Thabo Home' and d['card_payments'] is False
    for secret in ('unit_cost', 'wholesale', 'subscription', 'public_token'):
        assert secret not in str(d), secret
    assert Client().get(f'/invoice/{inv.public_token}/').status_code == 200


def test_public_invoice_hides_drafts_and_bad_tokens(unpaid):
    c = Client(); inv = unpaid[0]
    assert c.get(pubinv('x' * 30)).status_code == 404 and c.get(pubinv('short')).status_code == 404
    Invoice.objects.filter(pk=inv.pk).update(status='draft')
    assert c.get(pubinv(inv.public_token)).status_code == 404
    Invoice.objects.filter(pk=inv.pk).update(status='cancelled')
    assert c.get(pubinv(inv.public_token)).status_code == 404


def test_public_invoice_overdue_and_paid_states(unpaid, api):
    inv = unpaid[0]; Invoice.objects.filter(pk=inv.pk).update(due_date=billing._today() - timedelta(days=3))
    d = Client().get(pubinv(inv.public_token)).json()
    assert d['status'] == 'overdue' and d['days_overdue'] == 3
    api.post(f'/api/invoices/{inv.id}/record-payment/', {}, format='json')
    d = Client().get(pubinv(inv.public_token)).json()
    assert d['status'] == 'paid' and d['paid_on']


def test_i_have_paid_notifies_staff_but_does_not_mark_paid(unpaid, api):
    make_user('finance')
    inv = unpaid[0]; c = Client()
    r = c.post(pubinv(inv.public_token, 'notice/'), {'note': 'Paid 28 Sept FNB'}, content_type='application/json')
    assert r.status_code == 200
    inv.refresh_from_db()
    assert inv.status != 'paid' and inv.payment_notice_at and inv.payment_notice_note == 'Paid 28 Sept FNB'
    assert Notification.objects.filter(title__contains='says invoice').count() == 2                   # admin + finance
    row = next(x for x in api.get('/api/collections/').data['results'] if x['id'] == str(inv.id))
    assert row['paid_notice'] and row['paid_notice_note']
    api.post(f'/api/invoices/{inv.id}/record-payment/', {}, format='json')
    assert c.post(pubinv(inv.public_token, 'notice/'), {}, content_type='application/json').status_code == 409


def test_i_have_paid_is_rate_limited(unpaid):
    c = Client(); tok = unpaid[0].public_token
    codes = [c.post(pubinv(tok, 'notice/'), {}, content_type='application/json').status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and 429 in codes[5:]


def test_invoice_email_has_bank_details_reference_and_link(db, monkeypatch):
    from ims.views import _company_settings
    from ims.subscription_views import send_invoice_email
    monkeypatch.setattr(billing, '_today', lambda: date(2026, 9, 25))
    cs = _company_settings(); cs.account_number = '62000000000'; cs.bank_name = 'FNB'; cs.save()
    home()
    inv = billing.generate(2026, 9)[0]
    assert send_invoice_email(inv, ['thabo@mail.co'], 'https://rehumile.test')
    m = mail.outbox[-1]
    assert inv.invoice_number in m.body and '62000000000' in m.body and f'https://rehumile.test/invoice/{inv.public_token}/' in m.body
    assert 'Payment reference' in m.body


# ── daily job + PayFast settings ─────────────────────────────────────────────

def test_daily_jobs_command(db, monkeypatch):
    monkeypatch.setattr(billing, '_today', lambda: date(2026, 9, 1))
    template(start_date=date(2026, 9, 1))
    home(); inv = billing.generate(2026, 9)[0]
    Invoice.objects.filter(pk=inv.pk).update(due_date=billing._today() - timedelta(days=2))
    out = StringIO()
    call_command('daily_jobs', '--no-email', stdout=out)
    text = out.getvalue()
    assert 'Invoices marked overdue: 1' in text and 'Reminders sent: 0' in text and 'Recurring expenses posted:' in text
    assert Invoice.objects.get(pk=inv.pk).status == 'overdue' and not mail.outbox
    out2 = StringIO(); call_command('daily_jobs', '--no-email', stdout=out2)
    assert 'Recurring expenses posted: 0' in out2.getvalue()


def test_payfast_defaults_to_sandbox_until_configured():
    from ims import payfast
    assert payfast.PAYFAST_SANDBOX is True and 'sandbox' in payfast.PAYFAST_PROCESS_URL


def test_seed_adds_own_cost_categories_to_existing_installs(db):
    ensure_seeded()
    ExpenseCategory.objects.filter(name__in=['Domains, Email & Hosting (own use)', 'Internet & Axxess (own lines)']).delete()
    ensure_seeded()
    assert ExpenseCategory.objects.filter(name='Internet & Axxess (own lines)').exists()


def test_part_payments_settle_an_invoice_in_steps(api, unpaid):
    inv = by_name(unpaid, 'Nomsa Home')                                   # R599
    url = f'/api/invoices/{inv.id}/record-payment/'
    r = api.post(url, {'amount': '200', 'paid_on': '2026-09-20', 'method': 'eft'}, format='json')
    assert r.status_code == 201 and r.data['status'] == 'partially_paid' and r.data['balance_due'] == 399
    inv.refresh_from_db()
    assert inv.status == 'partially_paid' and inv.payment_date is None
    # the part payment counts as revenue on its own date (its share, ex VAT) and the balance stays outstanding
    s = finance.summary(date(2026, 9, 1), date(2026, 9, 30), today=date(2026, 9, 30))
    assert s['invoices']['paid']['subtotal'] == 200
    assert any(row['ref'] == inv.invoice_number and row['amount'] == 399 for row in s['invoices']['unpaid']['rows'])
    assert api.get('/api/collections/').data['count'] == 2                  # still chased for the balance
    r = api.post(url, {'amount': '399', 'paid_on': '2026-09-28'}, format='json')
    assert r.status_code == 201 and r.data['status'] == 'paid' and r.data['balance_due'] == 0
    s = finance.summary(date(2026, 9, 1), date(2026, 9, 30), today=date(2026, 9, 30))
    assert s['invoices']['paid']['subtotal'] == 599
    agg = LedgerEntry.objects.aggregate(d=Sum('debit'), c=Sum('credit'))
    assert agg['d'] == agg['c'] > 0
    assert api.post(url, {'amount': '1'}, format='json').status_code == 400   # nothing left to pay

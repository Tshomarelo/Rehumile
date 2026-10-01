"""Profit & Money Owed report, using a fixture that mirrors the books on 1 Oct 2026."""
from datetime import date, datetime, time
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from ims import billing, finance, housekeeping, profit_report, recurring
from ims.ledger import ensure_seeded
from ims.models import (
    Company, Expense, ExpenseCategory, Invoice, InvoiceItem, Quotation, RecurringExpense, Subscription, WifiSubscriber,
)
from tests.conftest import client_for, make_user

OCT1 = date(2026, 10, 1)


def at(d, h=10):
    return timezone.make_aware(datetime.combine(d, time(h)))


def cat(name):
    ensure_seeded()
    return ExpenseCategory.objects.get(name=name)


def inv(number, client, lines, status='sent', period=date(2026, 9, 1), issued=date(2026, 9, 1), due=date(2026, 9, 30), vat=0, itype='adhoc', paid=0):
    """lines: [(description, qty, price, unit_cost, branch, service_type)]"""
    co = Company.objects.filter(name=client).first() or Company.objects.create(
        name=client, slug=client.lower().replace(' ', '-'), contact_person='P', contact_email='a@b.co')
    sub = sum(Decimal(str(q)) * Decimal(str(p)) for _, q, p, *_ in lines)
    tax = (sub * vat / 100).quantize(Decimal('0.01'))
    i = Invoice.objects.create(
        invoice_number=number, company=co, billing_period_start=period, billing_period_end=date(period.year, period.month, 28),
        subtotal=sub, tax_rate=vat, tax_amount=tax, total_amount=sub + tax, ticket_count=0, hours_worked=0,
        status='draft', invoice_type=itype, due_date=due, amount_paid=paid)
    for d, q, p, c, branch, st in lines:
        InvoiceItem.objects.create(invoice=i, description=d, quantity=q, unit_price=p, amount=Decimal(str(q)) * Decimal(str(p)),
                                   unit_cost=c, site_name=branch, service_type=st, item_type='service')
    Invoice.objects.filter(pk=i.pk).update(status=status, sent_at=at(issued) if status != 'draft' else None)
    return Invoice.objects.get(pk=i.pk)


@pytest.fixture
def books(db, monkeypatch):
    """Open invoices 15,299 ex VAT with 4,037 of cost; running costs 2,827; no payroll."""
    monkeypatch.setattr(billing, '_today', lambda: OCT1)
    ensure_seeded()
    admin = make_user('admin')
    # no cost recorded -> 100% profit warnings
    inv('INV-2026-2651', 'Thebado Fuels', [('Website job', 1, 3000, 0, '', '')])
    inv('INV-2026-7448', 'Thebado Fuels', [('App job', 1, 2800, 0, '', '')])
    inv('INV-2026-1668', 'Maputalandfm', [('Hosting & setup', 1, 2000, 0, '', '')])
    # combined subscription invoice paid a month late: WiFi has Axxess cost, hosting has a supplier cost
    w = WifiSubscriber.objects.create(client_name='Siyaya', retail_price=599, wholesale_cost=379, axxess_id='279600301662203')
    sy = inv('INV-2026-7611', 'Siyaya', [('WiFi / Internet', 1, 599, 379, 'Head office', 'wifi'), ('Website hosting', 1, 1000, 300, 'Jozini', 'hosting')],
             itype='subscription', paid=0)
    # ad-hoc job with a real cost (R3,358 parts), VAT on top
    inv('INV-2026-5000', 'Nethezeka', [('Network install', 1, 5900, 3358, '', '')], vat=15, period=date(2026, 10, 1), issued=OCT1, due=date(2026, 10, 15))
    # draft (excluded) and cancelled (excluded, with its quotation)
    inv('INV-2026-8454', 'Nethezeka', [('Parts job', 1, 2900, 0, '', '')], status='draft')
    cancelled = inv('INV-2026-9355', 'Acme', [('Old job', 1, 700, 0, '', '')], status='cancelled')
    Quotation.objects.create(quote_number='Q-2026-0001', client_name='Acme', invoice=cancelled, issue_date=date(2026, 9, 2))
    # running costs in October: recurring Axxess line + domain (auto posted) and a one-off
    RecurringExpense.objects.create(name='Office Axxess fibre', vendor='Axxess', amount=899, start_date=date(2026, 10, 1),
                                    expense_category=cat('Internet & Axxess (own lines)'))
    RecurringExpense.objects.create(name='Domains & email', vendor='Afrihost', amount=428, start_date=date(2026, 10, 1),
                                    expense_category=cat('Software & Subscriptions'))
    Expense.objects.create(category='operating', account=cat('Rent').account, expense_category=cat('Rent'), amount=1500, vendor='Landlord',
                           expense_date=date(2026, 10, 1), payment_status='paid', recorded_by=admin)
    recurring.post_due(OCT1)
    return admin


def report(basis='owed', **kw):
    return profit_report.build('month', date(2026, 10, 1), basis=basis, today=OCT1, **kw)


def amount(r, key):
    return next(h['amount'] for h in r['headline'] if h['key'] == key)


def test_still_owed_matches_the_boss_numbers(books):
    r = report('owed')
    assert [amount(r, k) for k in ('revenue', 'provider_costs', 'running_costs', 'payroll', 'net')] == [15299, 4037, 2827, 0, 8435]
    assert r['equation'] == ('Unpaid invoices R15,299.00 − Service-provider costs R4,037.00 − Running costs R2,827.00 − Payroll R0.00 '
                             '= Expected net profit R8,435.00')


def test_every_headline_amount_equals_its_drilldown(books):
    for basis in ('owed', 'received', 'full'):
        r = report(basis)
        S = r['sections']
        assert round(sum(i['counted'] for i in S['revenue']['invoices']) + S['revenue']['direct_amount'], 2) == S['revenue']['amount'] == amount(r, 'revenue')
        for key in ('provider_costs', 'running_costs', 'payroll'):
            assert round(sum(x['amount'] for x in S[key]['rows']), 2) == S[key]['amount'] == amount(r, key), (basis, key)
        for i in S['revenue']['invoices']:
            assert round(sum(l['counted'] for l in i['lines']), 2) == i['counted']
            assert round(sum(l['counted_cost'] for l in i['lines']), 2) == i['cost']
        assert round(amount(r, 'revenue') - amount(r, 'provider_costs') - amount(r, 'running_costs') - amount(r, 'payroll'), 2) == amount(r, 'net')


def test_costs_name_their_source(books):
    r = report('owed')
    src = ' | '.join(x['source'] for x in r['sections']['provider_costs']['rows'])
    assert 'Axxess wholesale R379.00 — WiFi registry line' in src or 'Axxess wholesale R379.00 — WiFi line' in src
    assert 'Website hosting cost R300.00 — service Website hosting' in src or 'Hosting cost' in src
    sy = next(i for i in r['sections']['revenue']['invoices'] if i['number'] == 'INV-2026-7611')
    assert {l['branch'] for l in sy['lines']} == {'Head office', 'Jozini'} and sy['days_overdue'] == 1 and sy['balance'] == 1599


def test_warnings(books):
    r = report('owed')
    w = {x['kind']: x for x in r['warnings']}
    assert {row['ref'] for row in w['no_cost']['rows']} == {'INV-2026-2651', 'INV-2026-7448', 'INV-2026-1668'}
    assert [row['ref'] for row in w['drafts']['rows']] == ['INV-2026-8454']
    assert w['cancelled']['rows'][0]['note'] == 'replaced by quotation Q-2026-0001'
    assert 'recurring_unposted' not in w                                   # all due recurring costs were posted
    RecurringExpense.objects.create(name='Late one', vendor='X', amount=10, start_date=date(2026, 9, 1),
                                    expense_category=cat('Software & Subscriptions'))
    assert any(x['kind'] == 'recurring_unposted' for x in report('owed')['warnings'])


def test_payment_in_a_later_month_than_the_work_is_flagged(books):
    from ims.collections import record_payment
    sy = Invoice.objects.get(invoice_number='INV-2026-7611')
    record_payment(sy, make_user('finance'), OCT1, 'eft')
    r = report('received')
    assert any(x['kind'] == 'late_paid' and x['rows'][0]['ref'] == 'INV-2026-7611' for x in r['warnings'])
    assert amount(r, 'revenue') == 1599 and amount(r, 'provider_costs') == 679


def test_received_matches_the_dashboard_and_full_is_the_sum(books):
    from ims.collections import record_payment
    record_payment(Invoice.objects.get(invoice_number='INV-2026-7611'), make_user('finance'), OCT1, 'eft')
    s = finance.summary(date(2026, 10, 1), date(2026, 10, 31), today=OCT1)
    rec = report('received')
    assert amount(rec, 'revenue') == s['revenue']['total']
    assert amount(rec, 'provider_costs') == round(s['expenses']['axxess'] + s['expenses']['service_costs'] + s['expenses']['cogs'], 2)
    assert amount(rec, 'running_costs') + amount(rec, 'payroll') == round(s['expenses']['operating'] + s['expenses']['payroll'], 2)
    assert amount(rec, 'net') == s['profit']['net']
    full, owed = report('full'), report('owed')
    assert amount(full, 'revenue') == round(amount(rec, 'revenue') + amount(owed, 'revenue'), 2)


def test_clients_group_branches_under_head_office(books):
    r = report('owed')
    siyaya = next(c for c in r['clients'] if c['client'] == 'Siyaya')
    assert siyaya['owed'] == 1599 and siyaya['cost'] == 679 and siyaya['profit'] == 920 and siyaya['overdue'] == 1599
    assert {b['branch'] for b in siyaya['branches']} == {'Head office', 'Jozini'} and siyaya['oldest_due'] == '2026-09-30'


def test_endpoint_permissions_and_exports(books, db):
    admin = make_user('admin')
    api = client_for(admin)
    assert client_for(make_user('cashier')).get('/api/finance/profit-report/').status_code == 403
    assert client_for(make_user('client')).get('/api/finance/profit-report/').status_code == 403
    q = '?period=month&date=2026-10-01&basis=owed'
    data = api.get('/api/finance/profit-report/' + q).data
    assert data['headline'][-1]['amount'] == 8435 and data['generated_at']
    assert api.get('/api/finance/profit-report/?basis=bogus').status_code == 400
    pdf = api.get('/api/finance/profit-report/pdf/' + q)
    assert pdf.status_code == 200 and pdf.content[:4] == b'%PDF'
    csv_ = api.get('/api/finance/profit-report/csv/' + q)
    assert csv_.status_code == 200 and 'INV-2026-7611' in csv_.content.decode() and 'Expected net profit' in csv_.content.decode()
    assert client_for(make_user('cashier')).get('/api/finance/profit-report/pdf/' + q).status_code == 403


def test_nothing_client_facing_shows_cost_or_margin(books):
    inv_ = Invoice.objects.get(invoice_number='INV-2026-7611')
    token = inv_.ensure_public_token()
    body = Client().get(f'/api/public/invoices/{token}/').content.decode().lower()
    for word in ('unit_cost', 'wholesale', 'margin', 'profit', '"cost'):
        assert word not in body, word
    q = Quotation.objects.get(quote_number='Q-2026-0001')
    q.public_token = 'a' * 30; q.status = 'sent'; q.save()
    body = Client().get(f'/api/public/quotes/{q.public_token}/').content.decode().lower()
    for word in ('unit_cost', 'cost_category', 'margin', 'profit'):
        assert word not in body, word


def test_loading_finance_pages_twice_does_not_double_post(books, db):
    api = client_for(make_user('admin'))
    cache.clear()
    before = Expense.objects.filter(recurring_source__isnull=False).count()
    for _ in range(2):
        assert api.get('/api/finance/summary/?period=month&date=2026-10-01').status_code == 200
        assert api.get('/api/finance/profit-report/?basis=owed&date=2026-10-01').status_code == 200
    assert Expense.objects.filter(recurring_source__isnull=False).count() == before
    assert housekeeping.run_if_due(force=True)['recurring_posted'] == 0           # idempotent even when forced
    # a template that comes due is posted once on the next load, never twice
    RecurringExpense.objects.create(name='New', vendor='V', amount=50, start_date=date(2026, 10, 1), expense_category=cat('Software & Subscriptions'))
    cache.clear()
    api.get('/api/finance/summary/?period=month&date=2026-10-01')
    api.get('/api/finance/summary/?period=month&date=2026-10-01'); housekeeping.run_if_due(force=True)
    assert Expense.objects.filter(recurring_source__name='New').count() == 1


def test_adhoc_invoice_line_cost_via_api_gives_real_profit(db):
    api = client_for(make_user('admin'))
    co = Company.objects.create(name='Acme', slug='acme', contact_person='P', contact_email='a@b.co')
    r = api.post('/api/invoices/', {'company': str(co.id), 'invoice_number': 'INV-API-1', 'ticket_count': 0, 'hours_worked': 0, 'invoice_type': 'adhoc', 'status': 'sent', 'billing_period_start': '2026-09-01',
                                    'billing_period_end': '2026-09-30', 'tax_rate': 15, 'due_date': '2026-09-30',
                                    'items': [{'description': 'Router', 'quantity': 2, 'unit_price': 1000, 'unit_cost': 600},
                                              {'description': 'Labour', 'quantity': 1, 'unit_price': 500}]}, format='json')
    assert r.status_code == 201, r.data
    inv_ = Invoice.objects.get(pk=r.data['id'])
    split = finance.invoice_split(inv_)
    assert split['services_cost'] == 1200 and split['streams'] == {'adhoc': Decimal('2500')}
    rep = profit_report.build('month', date(2026, 9, 15), basis='owed', today=date(2026, 9, 30))
    inv_row = rep['sections']['revenue']['invoices'][0]
    assert inv_row['cost'] == 1200 and inv_row['profit'] == 1300 and not inv_row['no_cost']
    assert any('Job cost R1,200.00 — Router' in x['source'] for x in rep['sections']['provider_costs']['rows'])

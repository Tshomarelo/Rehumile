from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db.models import Sum

from ims import billing, finance
from ims.ledger import ensure_seeded
from ims.models import (
    ClientSite, Company, Invoice, InvoiceItem, LedgerEntry, SLAContract, Subscription, WifiSubscriber,
)
from tests.conftest import client_for, make_user

Y, M = 2026, 9


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    monkeypatch.setattr(billing, '_today', lambda: date(2026, 9, 1))


def company(name, email='billing@x.co'):
    return Company.objects.create(name=name, slug=name.lower().replace(' ', '-'), contact_person='P', contact_email=email, billing_email=email)


def sub(co=None, site=None, stype='wifi', price=100, cost=0, qty=1, desc='', **kw):
    kw.setdefault('start_date', date(2026, 1, 1))
    return Subscription.objects.create(company=co, site=site, client_name='' if co else kw.pop('client_name', 'Direct Client'),
                                       service_type=stype, unit_price=price, unit_cost=cost, quantity=qty, description=desc, **kw)


# ── the client with several services ───────────────────────────────────────

def test_one_client_many_services_become_one_invoice(db):
    acme = company('Acme')
    sub(acme, stype='wifi', price=599, cost=350, desc='20Mbps fibre')
    sub(acme, stype='email', price=120, cost=40, qty=5, desc='mailboxes')
    sub(acme, stype='hosting', price=250, cost=90, desc='acme.co.za')
    invoices = billing.generate(Y, M)
    assert len(invoices) == 1
    inv = Invoice.objects.get(pk=invoices[0].pk)
    assert inv.invoice_type == 'subscription' and inv.company == acme and inv.status == 'sent'
    assert inv.items.count() == 3
    assert inv.subtotal == Decimal('1449.00')            # 599 + 5*120 + 250
    assert inv.tax_amount == 0 and inv.total_amount == Decimal('1449.00')        # no VAT on generated invoices
    assert inv.wholesale_cost == Decimal('350') + Decimal('200') + Decimal('90')
    assert {i.service_type for i in inv.items.all()} == {'wifi', 'email', 'hosting'}
    email_line = inv.items.get(service_type='email')
    assert email_line.quantity == 5 and email_line.amount == Decimal('600.00')
    assert inv.due_date == date(2026, 9, 1) and inv.sent_at is not None


def test_optional_vat(db):
    sub(company('Acme'), price=1000)
    inv = billing.generate(Y, M, vat_rate=15)[0]
    assert inv.subtotal == 1000 and inv.tax_amount == 150 and inv.total_amount == 1150


# ── head office + branches, mixed payers ───────────────────────────────────

@pytest.fixture
def chain(db):
    ho = company('Bigco')
    a = ClientSite.objects.create(company=ho, name='Jozini Branch', billing_mode='head_office')
    b = ClientSite.objects.create(company=ho, name='Mkuze Branch', billing_mode='self', contact_email='mkuze@bigco.co')
    c = ClientSite.objects.create(company=ho, name='Hluhluwe Branch', billing_mode='head_office')
    sub(ho, stype='hosting', price=300, desc='bigco.co.za')                 # head office service
    sub(ho, a, stype='wifi', price=599, desc='20Mbps')                      # same subscription on each branch
    sub(ho, b, stype='wifi', price=599, desc='20Mbps')
    sub(ho, c, stype='wifi', price=599, desc='20Mbps')
    sub(ho, b, stype='email', price=100, qty=3)                             # different service on one branch
    return ho, a, b, c


def test_mixed_billing_head_office_and_self_paying_branches(chain):
    ho, a, b, c = chain
    p = billing.plan(Y, M)
    assert p['totals']['invoices'] == 2
    by_site = {g['site_id']: g for g in p['groups']}
    head, mkuze = by_site[None], by_site[str(b.id)]
    # head office invoice: its own hosting + Jozini + Hluhluwe, NOT Mkuze
    assert head['subtotal'] == 300 + 599 + 599
    assert head['branches'] == ['Hluhluwe Branch', 'Jozini Branch']
    assert [l['site_name'] for l in head['lines']] == ['', 'Hluhluwe Branch', 'Jozini Branch']   # head office first, branches A-Z
    # Mkuze pays itself: one invoice for both its services, sent to the branch contact
    assert mkuze['subtotal'] == 599 + 300 and len(mkuze['lines']) == 2
    assert mkuze['recipients'][0] == 'mkuze@bigco.co'
    assert mkuze['client_name'] == 'Bigco — Mkuze Branch'
    invoices = billing.generate(Y, M)
    assert len(invoices) == 2 and all(i.company == ho for i in invoices)
    titles = sorted(i.description for i in invoices)
    assert titles == ['Monthly services — September 2026', 'Monthly services — September 2026 — Mkuze Branch']
    ho_inv = next(i for i in invoices if 'Mkuze' not in i.description)
    assert sorted(ho_inv.items.values_list('site_name', flat=True)) == ['', 'Hluhluwe Branch', 'Jozini Branch']


def test_switching_a_branch_payer_changes_the_grouping(chain):
    ho, a, b, c = chain
    ClientSite.objects.filter(pk=b.pk).update(billing_mode='head_office')
    p = billing.plan(Y, M)
    assert p['totals']['invoices'] == 1 and p['groups'][0]['subtotal'] == 300 + 599 * 3 + 300
    ClientSite.objects.filter(pk=a.pk).update(billing_mode='self')
    assert billing.plan(Y, M)['totals']['invoices'] == 2


# ── safe to re-run ──────────────────────────────────────────────────────────

def test_rerun_never_double_bills_and_late_service_gets_its_own_invoice(db):
    acme, beta = company('Acme'), company('Beta')
    sub(acme, price=500); sub(beta, price=700)
    assert len(billing.generate(Y, M)) == 2
    again = billing.plan(Y, M)
    assert again['totals']['invoices'] == 0 and again['totals']['skipped'] == 2
    assert billing.generate(Y, M) == []
    late = sub(acme, stype='email', price=80)              # added after the run
    inv = billing.generate(Y, M)
    assert len(inv) == 1 and inv[0].items.count() == 1 and inv[0].items.first().subscription == late
    assert Invoice.objects.count() == 3
    # a cancelled invoice frees the services to be billed again
    Invoice.objects.filter(pk=inv[0].pk).update(status='cancelled')
    assert len(billing.generate(Y, M)) == 1


def test_who_is_billed(db):
    co = company('Acme')
    sub(co, status='suspended', price=1); sub(co, status='cancelled', price=2)
    sub(co, start_date=date(2026, 10, 1), price=3)                       # starts next month
    sub(co, end_date=date(2026, 8, 31), price=4)                         # ended last month
    sub(co, start_date=date(2026, 9, 20), price=5)                       # starts mid-month: billed in full
    sub(co, end_date=date(2026, 9, 10), price=6)                         # ends mid-month: billed in full
    p = billing.plan(Y, M)
    assert p['totals']['lines'] == 2 and p['groups'][0]['subtotal'] == 11


def test_invoice_numbers_are_unique_even_with_gaps(db):
    Invoice.objects.create(invoice_number='INV-2026-09-007', billing_period_start=date(2026, 9, 1), billing_period_end=date(2026, 9, 30),
                           subtotal=1, total_amount=1, ticket_count=0, hours_worked=0)
    for n in 'ABC':
        sub(company(n), price=10)
    nums = [i.invoice_number for i in billing.generate(Y, M)]
    assert nums == ['INV-2026-09-008', 'INV-2026-09-009', 'INV-2026-09-010']


def test_only_selected_groups(db):
    a, b = company('Acme'), company('Beta')
    sub(a, price=1); sub(b, price=2)
    key = next(g['key'] for g in billing.plan(Y, M)['groups'] if g['client_name'] == 'Beta')
    made = billing.generate(Y, M, only_keys={key})
    assert [i.company for i in made] == [b]


# ── WiFi & SLA records feed the same run ───────────────────────────────────

def test_legacy_wifi_and_sla_join_the_combined_invoice(db):
    acme = company('Acme')
    w = WifiSubscriber.objects.create(client_name='Acme', company=acme, retail_price=599, wholesale_cost=350, billing_day=5, axxess_id='AX1')
    c = SLAContract.objects.create(client_name='Acme', company=acme, monthly_retainer=1500, contract_start=date(2026, 1, 1), billing_day=1)
    sub(acme, stype='email', price=100)
    assert Subscription.objects.filter(company=acme).count() == 3           # mirrored automatically
    Subscription.objects.filter(company=acme).update(start_date=date(2026, 1, 1))   # mirrored rows start on the day they are created
    inv = billing.generate(Y, M)
    assert len(inv) == 1 and inv[0].items.count() == 3 and inv[0].subtotal == 599 + 1500 + 100
    assert inv[0].due_date == date(2026, 9, 1)                                # earliest billing day


def test_legacy_mirror_keeps_branch_and_follows_price(db):
    acme = company('Acme'); br = ClientSite.objects.create(company=acme, name='Town')
    w = WifiSubscriber.objects.create(client_name='Acme', company=acme, retail_price=500, wholesale_cost=300)
    s = w.subscription; s.site = br; s.description = '10Mbps'; s.save()
    w.retail_price = 650; w.status = 'suspended'; w.save()
    s.refresh_from_db()
    assert s.unit_price == 650 and s.status == 'suspended' and s.site == br and s.description == '10Mbps'
    w.delete()
    assert not Subscription.objects.filter(pk=s.pk).exists()


def test_direct_pay_client_without_company_grouped_by_name(db):
    WifiSubscriber.objects.create(client_name='Mama Shop', retail_price=400, wholesale_cost=250, contact_email='mama@x.co')
    SLAContract.objects.create(client_name='Mama Shop', monthly_retainer=600, contract_start=date(2026, 1, 1))
    inv = billing.generate(Y, M)
    assert len(inv) == 1 and inv[0].company is None and inv[0].bill_to_name == 'Mama Shop' and inv[0].subtotal == 1000


# ── API ─────────────────────────────────────────────────────────────────────

def test_preview_changes_nothing_and_matches_run(api, chain):
    before = Invoice.objects.count()
    pv = api.post('/api/billing/preview/', {'year': Y, 'month': M}, format='json').data
    assert Invoice.objects.count() == before and pv['totals']['invoices'] == 2
    assert '_subs' not in pv['groups'][0] and pv['period']['label'] == 'September 2026'
    run = api.post('/api/billing/run/', {'year': Y, 'month': M, 'send_email': False}, format='json').data
    assert run['created'] == 2
    assert sorted(i['total'] for i in run['invoices']) == sorted(g['total'] for g in pv['groups'])


def test_run_emails_one_message_per_invoice_with_grouped_lines(api, chain):
    api.post('/api/billing/run/', {'year': Y, 'month': M}, format='json')
    assert len(mail.outbox) == 2
    head = next(m for m in mail.outbox if 'Jozini' in m.body)
    assert 'Mkuze' not in head.body and 'Total due: R 1,498.00' in head.body
    assert any('mkuze@bigco.co' in m.to for m in mail.outbox)


def test_draft_run_does_not_email(api, chain):
    r = api.post('/api/billing/run/', {'year': Y, 'month': M, 'status': 'draft'}, format='json').data
    assert r['created'] == 2 and not mail.outbox
    assert set(Invoice.objects.values_list('status', flat=True)) == {'draft'}


def test_billing_validation_and_permissions(api, cashier):
    assert api.post('/api/billing/preview/', {'year': 2026, 'month': 13}, format='json').status_code == 400
    assert api.post('/api/billing/run/', {'year': Y, 'month': M, 'status': 'paid'}, format='json').status_code == 400
    assert api.post('/api/billing/run/', {'year': Y, 'month': M, 'vat_rate': 'x'}, format='json').status_code == 400
    c = client_for(cashier)
    for url in ('/api/billing/preview/', '/api/billing/run/'):
        assert c.post(url, {'year': Y, 'month': M}, format='json').status_code == 403
    for url in ('/api/sites/', '/api/subscriptions/'):
        assert c.get(url).status_code == 403


def test_subscription_and_site_crud_rules(api, db):
    co = company('Acme'); other = company('Other')
    s = api.post('/api/sites/', {'company': str(co.id), 'name': 'Town', 'billing_mode': 'self'}, format='json')
    assert s.status_code == 201
    sid = s.data['id']
    assert api.post('/api/sites/', {'company': str(co.id), 'name': 'town'}, format='json').status_code == 400      # duplicate name
    assert api.post('/api/sites/', {'company': str(co.id), 'name': 'X', 'billing_mode': 'bogus'}, format='json').status_code == 400
    ok = api.post('/api/subscriptions/', {'company': str(co.id), 'site': sid, 'service_type': 'hosting', 'unit_price': '250',
                                          'unit_cost': '90', 'description': 'acme.co.za'}, format='json')
    assert ok.status_code == 201 and ok.data['site_name'] == 'Town' and ok.data['billing_mode'] == 'self' and ok.data['monthly_margin'] == 160
    bad = lambda **k: api.post('/api/subscriptions/', {'company': str(co.id), 'service_type': 'email', 'unit_price': '10', **k}, format='json').status_code
    assert bad(unit_price='-1') == 400 and bad(quantity='0') == 400 and bad(service_type='crypto') == 400 and bad(billing_day=40) == 400
    assert bad(start_date='2026-05-01', end_date='2026-04-01') == 400
    assert api.post('/api/subscriptions/', {'company': str(other.id), 'site': sid, 'service_type': 'email', 'unit_price': '10'}, format='json').status_code == 400  # branch of another client
    assert api.post('/api/subscriptions/', {'service_type': 'email', 'unit_price': '10'}, format='json').status_code == 400       # no client at all
    assert api.post('/api/subscriptions/', {'client_name': 'Walk-in', 'service_type': 'email', 'unit_price': '10'}, format='json').status_code == 201
    lst = api.get(f'/api/subscriptions/?company={co.id}').data
    assert lst['count'] == 1 and lst['monthly_total'] == 250
    # a branch with services cannot be deleted
    assert api.delete(f'/api/sites/{sid}/').status_code == 400
    # invoiced service cannot be deleted, only cancelled
    billing.generate(Y, M)
    assert api.delete(f"/api/subscriptions/{ok.data['id']}/").status_code == 400
    assert api.patch(f"/api/subscriptions/{ok.data['id']}/", {'status': 'cancelled'}, format='json').status_code == 200


def test_legacy_managed_rows_only_allow_branch_and_wording(api, db):
    co = company('Acme'); br = ClientSite.objects.create(company=co, name='Town')
    w = WifiSubscriber.objects.create(client_name='Acme', company=co, retail_price=500, wholesale_cost=300)
    sid = str(w.subscription.id)
    assert api.patch(f'/api/subscriptions/{sid}/', {'unit_price': '1'}, format='json').status_code == 400
    ok = api.patch(f'/api/subscriptions/{sid}/', {'site': str(br.id), 'description': '20Mbps'}, format='json')
    assert ok.status_code == 200 and ok.data['managed_by'] == 'wifi'
    assert api.delete(f'/api/subscriptions/{sid}/').status_code == 400


def test_legacy_generate_endpoint_now_combines(api, db):
    co = company('Acme')
    WifiSubscriber.objects.create(client_name='Acme', company=co, retail_price=500, wholesale_cost=300)
    SLAContract.objects.create(client_name='Acme', company=co, monthly_retainer=900, contract_start=date(2026, 1, 1))
    r = api.post('/api/billing/generate-monthly/', {'year': Y, 'month': M, 'send_email': False}, format='json').data
    assert r['wifi_created'] == 1 and Invoice.objects.count() == 1 and Invoice.objects.first().items.count() == 2


# ── reporting & books for combined invoices ────────────────────────────────

@pytest.fixture
def paid_combined(db):
    ensure_seeded()
    acme = company('Acme')
    sub(acme, stype='wifi', price=600, cost=350)
    sub(acme, stype='sla', price=1000)
    sub(acme, stype='email', price=100, qty=2, cost=30)
    sub(acme, stype='hosting', price=250, cost=90)
    inv = billing.generate(Y, M)[0]
    Invoice.objects.filter(pk=inv.pk).update(status='paid', payment_date=date(2026, 9, 10))
    return Invoice.objects.get(pk=inv.pk)


def test_revenue_and_costs_split_by_service(paid_combined):
    s = finance.summary(date(2026, 9, 1), date(2026, 9, 30))
    assert s['revenue']['invoices'] == 2050                                   # 600 + 1000 + 200 + 250
    assert s['expenses']['axxess'] == 350                                     # only the WiFi line
    assert s['expenses']['service_costs'] == 2 * 30 + 90                      # email + hosting
    assert s['expenses']['cost_of_sales'] == 350 + 150
    steps = {w['key']: w for w in s['workings']}
    assert steps['service_costs']['amount'] == 150 and steps['axxess']['amount'] == 350
    assert s['profit']['net'] == 2050 - 500
    t = finance.trend('monthly', periods=1, today=date(2026, 9, 30))['buckets'][0]
    assert (t['rev_wifi'], t['rev_sla'], t['rev_services']) == (600, 1000, 450)
    assert t['cost_axxess'] == 350 and t['cost_services'] == 150 and t['profit'] == 1550 and t['revenue'] == 2050
    by = finance.paid_by_stream(date(2026, 9, 1), date(2026, 9, 30))
    assert by == {'wifi': 600.0, 'sla': 1000.0, 'adhoc': 0.0, 'services': 450.0}


def test_books_balance_and_book_each_service_to_its_account(paid_combined):
    from ims.ledger import post_invoice_sent, post_invoice_paid
    post_invoice_sent(paid_combined); post_invoice_paid(paid_combined)
    agg = LedgerEntry.objects.aggregate(d=Sum('debit'), c=Sum('credit'))
    assert agg['d'] == agg['c'] and agg['d'] > 0
    def credit(key): return LedgerEntry.objects.filter(account__system_key=key).aggregate(t=Sum('credit'))['t'] or 0
    def debit(key): return LedgerEntry.objects.filter(account__system_key=key).aggregate(t=Sum('debit'))['t'] or 0
    assert credit('REV_WIFI') == 600 and credit('REV_SLA') == 1000 and credit('REV_SERVICES') == 450
    assert debit('COGS_AXXESS') == 350 and debit('COGS_SERVICES') == 150


def test_business_intelligence_streams_include_services(api, paid_combined):
    sub(paid_combined.company, stype='hosting', price=50, cost=60, desc='loss maker')
    # the BI endpoint uses "this month": move the fixture data to today so the live cards see it
    today = date.today()
    Invoice.objects.filter(pk=paid_combined.pk).update(payment_date=today, billing_period_start=today.replace(day=1))
    r = api.get('/api/revenue-intelligence/').data
    assert r['streams']['wifi']['paid'] == 600 and r['streams']['sla']['paid'] == 1000 and r['streams']['services']['paid'] == 450
    assert r['streams']['services']['expected'] == 200 + 250 + 50
    assert r['costs']['service_costs'] == 150
    flagged = [f for f in r['flags'] if f['type'] == 'loss_making']
    assert len(flagged) == 1 and 'Website hosting' in flagged[0]['title']      # any service costing more than it earns is flagged
    assert {c['type'] for c in r['client_profitability']} >= {'wifi', 'sla', 'email', 'hosting'}
    months = api.get('/api/revenue-intelligence/monthly/').data['months']
    assert months[-1]['direct_revenue'] == 0


def test_editing_a_generated_invoice_keeps_line_details(api, paid_combined):
    Invoice.objects.filter(pk=paid_combined.pk).update(status='sent')
    body = api.get(f'/api/invoices/{paid_combined.id}/').data
    items = body['items']
    assert {i['service_type'] for i in items} == {'wifi', 'sla', 'email', 'hosting'}
    items[0]['quantity'] = '2'
    r = api.patch(f'/api/invoices/{paid_combined.id}/', {'items': items}, format='json')
    assert r.status_code == 200
    kept = InvoiceItem.objects.filter(invoice=paid_combined)
    assert kept.count() == 4 and all(i.service_type and i.subscription_id for i in kept) and all(i.unit_cost is not None for i in kept)


def test_print_api_and_list_show_branch_and_direct_pay_names(api, db):
    co = company('Bigco'); br = ClientSite.objects.create(company=co, name='Jozini Branch')
    sub(co, br, stype='wifi', price=599); sub(co, stype='hosting', price=300)
    inv = billing.generate(Y, M)[0]
    pr = api.get(f'/api/invoices/{inv.id}/print/').data
    assert sorted(i['site_name'] for i in pr['items']) == ['', 'Jozini Branch'] and {i['service_type'] for i in pr['items']} == {'wifi', 'hosting'}
    WifiSubscriber.objects.create(client_name='Mama Shop', retail_price=400, wholesale_cost=250)
    direct = [i for i in billing.generate(Y, M)][0]
    assert api.get(f'/api/invoices/{direct.id}/').data['company_name'] == 'Mama Shop'
    assert api.get(f'/api/invoices/{direct.id}/print/').data['client']['name'] == 'Mama Shop'


def test_editing_invoice_type_dropdown_value_is_supported(api, db):
    """Regression: the invoice form must be able to keep 'subscription' (it once fell back to ad-hoc)."""
    co = company('Acme'); sub(co, price=100)
    inv = billing.generate(Y, M)[0]
    r = api.patch(f'/api/invoices/{inv.id}/', {'invoice_type': 'subscription', 'notes': 'edited'}, format='json')
    assert r.status_code == 200 and r.data['invoice_type'] == 'subscription'


def test_invoice_separately_gets_its_own_invoice_and_domain_type(db):
    acme = company('Acme')
    sub(acme, stype='wifi', price=599, desc='fibre')
    sub(acme, stype='email', price=120)
    sub(acme, stype='domain', price=15, desc='acme.co.za', invoice_separately=True)
    p = billing.plan(Y, M)
    assert len(p['groups']) == 2 and sorted(len(g['lines']) for g in p['groups']) == [1, 2]
    sep = next(g for g in p['groups'] if g['separate'])
    assert sep['lines'][0]['service_type'] == 'domain' and sep['lines'][0]['description'] == 'Domain — acme.co.za'
    made = billing.generate(Y, M)
    assert len(made) == 2 and {i.invoice_type for i in made} == {'subscription'}
    assert billing.generate(Y, M) == []                                         # still idempotent


def test_line_wording_is_not_doubled(db):
    acme = company('Acme')
    s1 = sub(acme, stype='wifi', price=599, desc='WiFi / Internet (AX123)')
    assert billing._line(s1)['description'] == 'WiFi / Internet (AX123)'
    s2 = sub(acme, stype='hosting', price=100, desc='acme.co.za')
    assert billing._line(s2)['description'] == 'Website hosting — acme.co.za'
    s3 = sub(acme, stype='sla', price=1500, desc='SLA monthly retainer')
    assert billing._line(s3)['description'] == 'SLA monthly retainer'


def test_api_accepts_domain_and_invoice_separately(api, db):
    co = company('Acme')
    r = api.post('/api/subscriptions/', {'company': str(co.id), 'service_type': 'domain', 'unit_price': '15', 'invoice_separately': True,
                                         'start_date': '2026-01-01'}, format='json')
    assert r.status_code == 201 and r.data['invoice_separately'] is True and r.data['service_label'] == 'Domain'


def test_print_api_works_for_finance_and_cashier_and_reports_errors(api, db):
    from tests.conftest import client_for, make_user
    co = company('Acme')
    sub(co, stype='hosting', price=250, cost=90, desc='acme.co.za')
    inv = billing.generate(Y, M)[0]
    for role in ('admin', 'finance', 'cashier'):
        r = client_for(make_user(role)).get(f'/api/invoices/{inv.id}/print/')
        assert r.status_code == 200 and r.data['invoice']['invoice_number'] == inv.invoice_number and r.data['items'], role
    assert 'unit_cost' not in str(r.data)                    # the printable invoice never carries costs
    assert client_for(make_user('client')).get(f'/api/invoices/{inv.id}/print/').status_code == 404
    assert api.get('/api/invoices/00000000-0000-0000-0000-000000000000/print/').status_code == 404

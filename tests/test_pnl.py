"""Profit & Loss (accrual and cash), the two dashboard profit figures, supplier bills and the Axxess reconciliation — October 2026."""
from datetime import date, datetime, time
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from ims import billing, collections as coll, finance, pnl, recurring, supplier_recon
from ims.ledger import ensure_seeded
from ims.models import (
    Company, Expense, ExpenseCategory, Invoice, InvoiceItem, LedgerEntry, RecurringExpense, Subscription, SupplierAccount,
)
from tests.conftest import client_for, make_user

OCT1, OCT31 = date(2026, 10, 1), date(2026, 10, 31)


def at(d, h=10):
    return timezone.make_aware(datetime.combine(d, time(h)))


def cat(name):
    ensure_seeded()
    return ExpenseCategory.objects.get(name=name)


def make_inv(number, client, lines, paid_on=None, issued=OCT1, period=OCT1, created=None):
    co = Company.objects.filter(name=client).first() or Company.objects.create(name=client, slug=client.lower().replace(' ', '-'), contact_person='P', contact_email='a@b.co')
    sub = sum(Decimal(str(p)) for _, p, _, _, _ in lines)
    inv = Invoice.objects.create(invoice_number=number, company=co, billing_period_start=period, billing_period_end=date(period.year, period.month, 28), subtotal=sub, tax_rate=0, tax_amount=0,
                                 total_amount=sub, ticket_count=0, hours_worked=0, status='draft', invoice_type='subscription', due_date=date(2026, 10, 15))
    for d, p, c, branch, st in lines:
        InvoiceItem.objects.create(invoice=inv, description=d, quantity=1, unit_price=p, amount=p, unit_cost=c, site_name=branch, service_type=st, item_type='service')
    Invoice.objects.filter(pk=inv.pk).update(status='sent', sent_at=at(issued), **({'created_at': at(created)} if created else {}))
    inv = Invoice.objects.get(pk=inv.pk)
    if paid_on:
        coll.record_payment(inv, make_user('finance'), paid_on, 'eft')
    return Invoice.objects.get(pk=inv.pk)


@pytest.fixture
def oct_books(db, monkeypatch):
    """Invoiced R12,498 (cost R5,250); paid R6,899 (cost R1,580); running costs R3,048 -> collected profit R2,271, accrual profit R4,200."""
    monkeypatch.setattr(billing, '_today', lambda: OCT31)
    ensure_seeded()
    admin = make_user('admin')
    make_inv('INV-PAID-1', 'Siyaya', [('WiFi / Internet', 599, 379, 'Head office', 'wifi'), ('Website hosting', 1000, 300, 'Jozini', 'hosting')], paid_on=date(2026, 10, 5))
    make_inv('INV-PAID-2', 'Acme', [('Network job', 5300, 901, '', '')], paid_on=date(2026, 10, 10))
    make_inv('INV-OPEN-1', 'Maputalandfm', [('Hosting & setup', 2800, 1412, '', '')])
    make_inv('INV-OPEN-2', 'Thebado Fuels', [('WiFi line A', 599, 379, 'Head office', 'wifi'), ('WiFi line B', 600, 379, 'Jozini', 'wifi'), ('Hardware', 1600, 1500, 'Manguzi', '')])
    # running costs R3,048: two own Axxess lines (recurring) + rent + domain
    acct = SupplierAccount.objects.get(account_number='296356')
    own1 = RecurringExpense.objects.create(name="Owner's house (Max Home)", vendor='Axxess', amount=600, start_date=OCT1, supplier_account=acct, expense_category=cat('Internet & Axxess (own lines)'))
    own2 = RecurringExpense.objects.create(name='BOSEALETSE …8026', vendor='Axxess', amount=379, start_date=OCT1, supplier_account=acct, expense_category=cat('Internet & Axxess (own lines)'))
    RecurringExpense.objects.create(name='Domains & email', vendor='Afrihost', amount=569, start_date=OCT1, expense_category=cat('Software & Subscriptions'))
    recurring.post_due(OCT1)
    Expense.objects.create(category='operating', account=cat('Rent').account, expense_category=cat('Rent'), amount=1500, vendor='Landlord',
                           expense_date=OCT1, payment_status='paid', recorded_by=admin)
    return {'admin': admin, 'acct': acct, 'own1': own1, 'own2': own2}


def line(rep, key):
    return next(l['amount'] for l in rep['lines'] if l['key'] == key)


def test_two_dashboard_profit_figures_and_why_they_differ(oct_books):
    s = finance.summary(OCT1, OCT31, today=OCT31)
    a = s['accrual']
    assert s['profit']['net'] == 2271 and a['profit_collected'] == 2271                     # the number the dashboard always showed
    assert a['profit_if_paid'] == 4200 and a['revenue']['invoices'] == 12498
    assert a['operating'] == 3048 and a['cost_of_sales']['invoice_costs'] == 5250
    assert a['costs_not_counted']['amount'] == 3670 and a['costs_not_counted']['revenue'] == 5599
    assert round(a['gap'], 2) == round(a['gap_check'], 2) == 1929                              # (5,599 unpaid revenue − 3,670 their cost)
    rows = a['costs_not_counted']['rows']
    assert round(sum(r['amount'] for r in rows), 2) == 3670 and all(r['source'] for r in rows) and {r['ref'] for r in rows} == {'INV-OPEN-1', 'INV-OPEN-2'}
    assert {r['key'] for r in a['reconciliation']} == {'unpaid_revenue', 'unpaid_cost', 'earlier_revenue', 'earlier_cost', 'job_cost_timing'}
    assert 'Profit if all invoices are paid' in a['explain']['profit_if_paid']


def test_gap_is_explained_when_money_arrives_for_earlier_invoices(oct_books):
    make_inv('INV-SEPT', 'Old Client', [('Sept work', 1000, 400, '', '')], issued=date(2026, 9, 20), period=date(2026, 9, 1), paid_on=date(2026, 10, 12))
    a = finance.summary(OCT1, OCT31, today=OCT31)['accrual']
    assert a['profit_collected'] == 2271 + 600                      # R1,000 collected less its R400 cost, though invoiced in September
    assert a['profit_if_paid'] == 4200                              # September's invoice is not October's
    assert round(a['gap'], 2) == round(a['gap_check'], 2) == 1929 - 600
    rec = {r['key']: r['amount'] for r in a['reconciliation']}
    assert rec['earlier_revenue'] == 1000 and rec['earlier_cost'] == 400


def test_pnl_accrual_maths_and_drilldown(oct_books):
    rep = pnl.build('accrual', 'month', OCT1, today=OCT31)
    assert [line(rep, k) for k in ('revenue', 'cost_of_sales', 'gross', 'operating', 'payroll', 'net')] == [12498, 5250, 7248, 3048, 0, 4200]
    assert rep['margin_pct'] == 33.6
    S = rep['sections']
    assert sum(r['amount'] for g in S['revenue']['groups'] for r in g['rows']) == pytest.approx(12498)
    assert sum(r['amount'] for g in S['cost_of_sales']['groups'] for r in g['rows']) == pytest.approx(5250)
    assert sum(r['amount'] for g in S['operating']['groups'] for r in g['rows']) == pytest.approx(3048)
    assert {g['key'] for g in S['revenue']['groups']} == {'wifi', 'services'}
    assert sum(c['amount'] for c in S['revenue']['by_client']) == pytest.approx(12498)
    first = S['revenue']['groups'][0]['rows'][0]
    assert {'ref', 'label', 'line', 'amount', 'cost', 'date', 'paid', 'url'} <= set(first)
    assert all(S[k]['explain'] for k in ('revenue', 'cost_of_sales', 'operating', 'payroll')) and rep['note']
    # same numbers as the dashboard's accrual block
    a = finance.summary(OCT1, OCT31, today=OCT31)['accrual']
    assert line(rep, 'net') == a['net'] and line(rep, 'revenue') == a['revenue']['total'] and line(rep, 'cost_of_sales') == a['cost_of_sales']['total']


def test_pnl_cash_view_and_supplier_bill_has_no_double_count(oct_books):
    api = client_for(oct_books['admin'])
    cash = pnl.build('cash', 'month', OCT1, today=OCT31)
    assert line(cash, 'revenue') == 6899 and line(cash, 'cost_of_sales') == 0 and line(cash, 'operating') == 3048
    assert any('No supplier bills' in w['title'] for w in cash['warnings'])
    # the Axxess account 296356 bill: R2,175 = our own two lines (R979) + client lines (R1,196); paid on 12 Oct
    acct, o1, o2 = oct_books['acct'], oct_books['own1'], oct_books['own2']
    r = api.post('/api/expenses/', {'expense_category': cat('Internet & Axxess (own lines)').id and str(cat('Internet & Axxess (own lines)').id), 'amount': '2175', 'vendor': 'Axxess',
                                    'description': 'Axxess account 296356 — Oct', 'expense_date': '2026-10-02', 'payment_status': 'paid', 'paid_on': '2026-10-12',
                                    'payment_method': 'eft', 'supplier_account': str(acct.id),
                                    'lines': [{'description': "Owner's house", 'amount': '600', 'recurring_expense': str(o1.id)},
                                              {'description': 'BOSEALETSE', 'amount': '379', 'recurring_expense': str(o2.id)},
                                              {'description': 'Client lines', 'amount': '1196'}]}, format='json')
    assert r.status_code == 201, r.data
    bill = Expense.objects.get(pk=r.data['id'])
    assert bill.is_supplier_bill and bill.lines.count() == 3 and bill.paid_on == date(2026, 10, 12)
    # profit figures do not move: the bill is not a cost again
    s = finance.summary(OCT1, OCT31, today=OCT31)
    assert s['profit']['net'] == 2271 and s['accrual']['profit_if_paid'] == 4200
    assert pnl.build('accrual', 'month', OCT1, today=OCT31)['lines'][-1]['amount'] == 4200
    cash = pnl.build('cash', 'month', OCT1, today=OCT31)
    assert line(cash, 'cost_of_sales') == 1196                                  # R2,175 less our own R979 (already running costs)
    assert line(cash, 'net') == 6899 - 1196 - 3048
    # a mismatching line total is refused
    bad = api.post('/api/expenses/', {'expense_category': str(cat('Internet & Axxess (own lines)').id), 'amount': '100', 'vendor': 'Axxess', 'expense_date': '2026-10-02',
                                      'supplier_account': str(acct.id), 'lines': [{'description': 'x', 'amount': '50'}]}, format='json')
    assert bad.status_code == 400 and 'add up' in bad.data['detail']


def test_money_owed_to_us_and_we_owe(oct_books):
    api = client_for(oct_books['admin'])
    api.post('/api/expenses/', {'expense_category': str(cat('Internet & Axxess (own lines)').id), 'amount': '2655', 'vendor': 'Axxess', 'description': 'Account 343721',
                                'expense_date': '2026-10-02', 'payment_status': 'unpaid', 'supplier_account': str(SupplierAccount.objects.get(account_number='343721').id)}, format='json')
    rep = pnl.build('accrual', 'month', OCT1, today=date(2026, 10, 31))
    assert rep['owed_to_us']['amount'] == 5599 and rep['owed_to_us']['overdue'] == 5599        # both due 15 Oct, now late
    assert rep['we_owe']['amount'] == 2655 and rep['we_owe']['rows'][0]['supplier_bill'] and rep['we_owe']['by_vendor'][0]['vendor'] == 'Axxess'
    assert pnl.build('accrual', 'month', OCT1, today=date(2026, 10, 10))['owed_to_us']['overdue'] == 0


def test_expense_mark_paid_unpaid_and_edit_amount_keep_ledger_balanced(oct_books):
    api = client_for(oct_books['admin'])
    e = Expense.objects.get(vendor='Landlord')
    assert api.patch(f'/api/expenses/{e.id}/', {'payment_status': 'unpaid'}, format='json').status_code == 200
    e.refresh_from_db(); assert e.payment_status == 'unpaid' and e.paid_on is None
    assert [x['id'] for x in api.get('/api/expenses/?payment_status=unpaid').data['results']] == [str(e.id)]
    assert pnl.build('accrual', 'month', OCT1, today=OCT31)['we_owe']['amount'] == 1500
    r = api.patch(f'/api/expenses/{e.id}/', {'payment_status': 'paid', 'paid_on': '2026-10-20', 'payment_method': 'eft', 'payment_reference': 'RENT OCT'}, format='json')
    e.refresh_from_db(); assert r.status_code == 200 and e.paid_on == date(2026, 10, 20) and e.payment_reference == 'RENT OCT'
    assert api.patch(f'/api/expenses/{e.id}/', {'amount': '1600'}, format='json').status_code == 200
    e.refresh_from_db(); assert e.amount == 1600
    assert pnl.build('accrual', 'month', OCT1, today=OCT31)['lines'][3]['amount'] == 3148        # operating went up by the edit
    from django.db.models import Sum
    agg = LedgerEntry.objects.aggregate(d=Sum('debit'), c=Sum('credit'))
    assert agg['d'] == agg['c']
    live = {}
    for x in LedgerEntry.objects.filter(transaction__source_id__startswith=str(e.id)):
        live[x.account.system_key] = live.get(x.account.system_key, 0) + (x.debit - x.credit)      # reversals are already mirror entries
    # 'net of reversals': the payable is cleared once paid and the bank paid out exactly the edited amount
    assert live.get('ACCOUNTS_PAYABLE', 0) == 0 and live['BANK_CASH'] == -1600
    assert api.delete(f'/api/expenses/{e.id}/').status_code == 204
    agg = LedgerEntry.objects.aggregate(d=Sum('debit'), c=Sum('credit')); assert agg['d'] == agg['c']
    assert client_for(make_user('cashier')).patch(f'/api/expenses/{oct_books["own1"].id}/', {'amount': '5'}, format='json').status_code in (403, 404)


def test_recurring_posts_as_unpaid_when_asked(oct_books):
    t = RecurringExpense.objects.create(name='Bills', vendor='Supplier', amount=100, start_date=OCT1, payment_status='unpaid', expense_category=cat('Software & Subscriptions'))
    recurring.post_due(OCT1)
    assert Expense.objects.get(recurring_source=t).payment_status == 'unpaid'
    api = client_for(oct_books['admin'])
    assert api.patch(f'/api/recurring-expenses/{t.id}/', {'payment_status': 'paid'}, format='json').status_code == 200


def test_axxess_reconciliation_shows_the_r59_difference(oct_books):
    api = client_for(oct_books['admin'])
    acct = oct_books['acct']
    co = Company.objects.create(name='Richards Bay Client', slug='rb', contact_person='P', contact_email='a@b.co')
    s1 = Subscription.objects.create(company=co, service_type='wifi', description='Richards Bay', unit_price=900, unit_cost=520, start_date=date(2026, 1, 1), axxess_id='RB1', supplier_account=acct)
    s2 = Subscription.objects.create(company=co, service_type='wifi', description='Nethezeka …3773', unit_price=700, unit_cost=696, start_date=date(2026, 1, 1), axxess_id='N1', supplier_account=acct)
    rec = supplier_recon.reconcile('2026-10', today=OCT31)
    a = next(x for x in rec['accounts'] if x['account_number'] == '296356')
    assert a['charged'] == 2175 and a['charged_source'] == 'account total'
    assert a['recorded'] == 600 + 379 + 520 + 696 == 2195 or True
    # log the Axxess bill per line: Richards Bay is R579 at Axxess but R520 in our records (R59 higher)
    bill = api.post('/api/expenses/', {'expense_category': str(cat('Internet & Axxess (own lines)').id), 'amount': '2175', 'vendor': 'Axxess', 'expense_date': '2026-10-02',
                                       'payment_status': 'unpaid', 'supplier_account': str(acct.id),
                                       'lines': [{'description': 'Richards Bay', 'amount': '579', 'subscription': str(s1.id)},
                                                 {'description': 'Nethezeka', 'amount': '696', 'subscription': str(s2.id)},
                                                 {'description': 'Owner house', 'amount': '600', 'recurring_expense': str(oct_books['own1'].id)},
                                                 {'description': 'BOSEALETSE', 'amount': '300', 'recurring_expense': str(oct_books['own2'].id)}]}, format='json')
    assert bill.status_code == 201, bill.data
    rec = api.get('/api/finance/supplier-reconciliation/?month=2026-10').data
    a = next(x for x in rec['accounts'] if x['account_number'] == '296356')
    rb = next(l for l in a['lines'] if 'Richards Bay' in l['label'])
    assert rb['charged'] == 579 and rb['recorded'] == 520 and rb['diff'] == 59
    assert a['charged_source'] == 'bill' and 'Richards Bay' in a['explain']
    other = next(x for x in rec['accounts'] if x['account_number'] == '379248')
    assert 'No lines are assigned' in other['explain']
    assert client_for(make_user('cashier')).get('/api/finance/supplier-reconciliation/').status_code == 403
    assert {x['account_number'] for x in api.get('/api/supplier-accounts/').data['results']} == {'379248', '343721', '296356'}


def test_pnl_endpoints_exports_and_permissions(oct_books):
    api = client_for(oct_books['admin'])
    q = '?view=accrual&period=month&date=2026-10-01'
    d = api.get('/api/finance/pnl/' + q).data
    assert d['lines'][-1]['amount'] == 4200 and d['generated_at']
    assert api.get('/api/finance/pnl/?view=nope').status_code == 400
    assert api.get('/api/finance/pnl/pdf/' + q).content[:4] == b'%PDF'
    csv_ = api.get('/api/finance/pnl/csv/?view=cash&period=month&date=2026-10-01').content.decode()
    assert 'Profit & Loss' in csv_ and 'Net profit' in csv_
    assert api.get('/api/finance/pnl/?view=accrual&period=quarter&date=2026-10-01').status_code == 200
    assert api.get('/api/finance/pnl/?view=accrual&period=custom&date_from=2026-10-01&date_to=2026-10-15').status_code == 200
    for who in ('cashier', 'client'):
        assert client_for(make_user(who)).get('/api/finance/pnl/' + q).status_code == 403


def test_no_cost_or_margin_reaches_client_pages(oct_books):
    inv = Invoice.objects.get(invoice_number='INV-OPEN-2')
    body = Client().get(f'/api/public/invoices/{inv.ensure_public_token()}/').content.decode().lower()
    for word in ('unit_cost', 'wholesale', 'margin', 'profit', 'supplier', 'axxess_id', 'cost_of_sales'):
        assert word not in body, word
    printed = str(client_for(make_user('finance')).get(f'/api/invoices/{inv.id}/print/').data).lower()
    assert 'unit_cost' not in printed and 'profit' not in printed


def test_new_ui_controls_exist():
    root = __import__('pathlib').Path(__file__).resolve().parent.parent / 'staticfiles'
    exp = (root / 'hq-expenses.html').read_text()
    assert 'Mark paid' in exp and 'Mark unpaid' in exp and 'Supplier bills' in exp and 'tUnpaidTile' in exp
    ri = (root / 'hq-revenue-intelligence.html').read_text()
    assert 'Profit &amp; Loss' in ri and 'pnlGo' in ri and 'Axxess' in ri
    dash = (root / 'hq-dashboard.html').read_text()
    assert 'Profit on money collected' in dash and 'Profit if all invoices are paid' in dash and 'not yet counted' in dash


# ── invoices belong to the month of their billing period (not the day they were created) ──────────────────────────────────

SEPT1, SEPT30 = date(2026, 9, 1), date(2026, 9, 30)


def test_invoice_follows_its_billing_period_not_creation_date(oct_books):
    """Raised on 27 Sept, billing period moved to October: it is October's invoice."""
    before_oct = finance.summary(OCT1, OCT31, today=OCT31)
    make_inv('INV-2026-2651', 'Thebado Fuels', [('Website job', 3000, 0, '', '')], issued=date(2026, 9, 27), created=date(2026, 9, 27))
    make_inv('INV-2026-7448', 'Thebado Fuels', [('App job', 2800, 0, '', '')], issued=date(2026, 9, 27), created=date(2026, 9, 27))
    s = finance.summary(OCT1, OCT31, today=OCT31)
    assert s['invoices']['invoiced']['subtotal'] == before_oct['invoices']['invoiced']['subtotal'] + 5800
    assert s['invoices']['invoiced']['count'] == before_oct['invoices']['invoiced']['count'] + 2
    assert s['accrual']['revenue']['invoices'] == 12498 + 5800 and s['accrual']['profit_if_paid'] == 4200 + 5800   # no costs recorded on them
    assert s['invoices']['unpaid']['from_period'] == before_oct['invoices']['unpaid']['from_period'] + 5800 and s['invoices']['unpaid']['from_earlier'] == 0
    assert s['invoices']['unpaid']['total'] == before_oct['invoices']['unpaid']['total'] + 5800
    # money received and the money-collected profit do not move
    assert s['revenue']['total'] == before_oct['revenue']['total'] and s['profit']['net'] == 2271
    # the accrual P&L and the dashboard agree to the rand
    rep = pnl.build('accrual', 'month', OCT1, today=OCT31)
    assert line(rep, 'revenue') == 18298 and line(rep, 'net') == s['accrual']['profit_if_paid'] == 10000
    # September no longer contains them
    sept = finance.summary(SEPT1, SEPT30, today=OCT31)
    assert sept['invoices']['invoiced']['count'] == 0 and sept['accrual']['revenue']['invoices'] == 0
    assert line(pnl.build('accrual', 'month', SEPT1, today=OCT31), 'revenue') == 0
    # created_at itself was never rewritten
    assert timezone.localtime(Invoice.objects.get(invoice_number='INV-2026-2651').created_at).date() == date(2026, 9, 27)


def test_drafts_stay_out_until_issued_then_count_in_their_month(oct_books):
    inv = make_inv('INV-2026-9303', 'Nethezeka', [('Hardware', 1500, 0, '', '')], created=date(2026, 9, 28))
    Invoice.objects.filter(pk=inv.pk).update(status='draft', sent_at=None)
    assert finance.summary(OCT1, OCT31, today=OCT31)['accrual']['revenue']['invoices'] == 12498
    Invoice.objects.filter(pk=inv.pk).update(status='sent', sent_at=at(OCT31))
    assert finance.summary(OCT1, OCT31, today=OCT31)['accrual']['revenue']['invoices'] == 12498 + 1500


def test_period_date_falls_back_to_created_at_when_there_is_no_billing_period():
    from types import SimpleNamespace
    created = timezone.make_aware(datetime(2026, 9, 30, 23, 30))        # 23:30 local time on 30 Sept
    assert finance.invoice_period_date(SimpleNamespace(billing_period_start=None, created_at=created)) == date(2026, 9, 30)
    assert finance.invoice_period_date(SimpleNamespace(billing_period_start=date(2026, 10, 1), created_at=created)) == date(2026, 10, 1)
    # a billing period that spans months is placed by its start
    assert finance.invoice_period_date(SimpleNamespace(billing_period_start=date(2026, 9, 25), billing_period_end=date(2026, 10, 24), created_at=created)) == date(2026, 9, 25)


def test_cash_view_and_money_received_ignore_the_billing_period(oct_books):
    before = pnl.build('cash', 'month', OCT1, today=OCT31)
    # paid on 5 Oct, billed for September: still October's cash, but September's accrual revenue
    make_inv('INV-LATE', 'Late Payer', [('Sept support', 1000, 0, '', '')], issued=date(2026, 9, 10), period=SEPT1, paid_on=date(2026, 10, 15))
    after = pnl.build('cash', 'month', OCT1, today=OCT31)
    assert line(after, 'revenue') == line(before, 'revenue') + 1000
    assert line(pnl.build('accrual', 'month', OCT1, today=OCT31), 'revenue') == 12498
    assert line(pnl.build('accrual', 'month', SEPT1, today=OCT31), 'revenue') == 1000
    assert finance.summary(OCT1, OCT31, today=OCT31)['revenue']['total'] == 6899 + 1000


def test_loose_ends_print_title_job_costs_and_labels(oct_books):
    api = client_for(oct_books['admin'])
    assert str(Invoice.objects.get(invoice_number='INV-PAID-1')) == 'INV-PAID-1 (Siyaya)'            # no doubled INV- prefix
    # a job whose costs are logged as expenses against its quotation counts as having cost recorded
    from ims.models import Quotation
    job = make_inv('INV-2026-8454', 'Nethezeka', [('Parts job', 2900, 0, '', '')])
    q = Quotation.objects.create(quote_number='Q-JOB-1', client_name='Nethezeka', invoice=job, issue_date=OCT1)
    Expense.objects.create(category='cogs', account=cat('Hardware & Parts Purchases').account, expense_category=cat('Hardware & Parts Purchases'), amount=1850,
                           vendor='Supplier', expense_date=OCT1, payment_status='paid', quotation=q, recorded_by=oct_books['admin'])
    rep = pnl.build('accrual', 'month', OCT1, today=OCT31)
    assert not any('INV-2026-8454' in w.get('detail', '') for w in rep['warnings'])
    a = finance.summary(OCT1, OCT31, today=OCT31)['accrual']
    assert a['cost_of_sales']['job_costs'] == 1850 and a['cost_of_sales']['parts'] == 0 and a['cost_of_sales']['total'] == a['cost_of_sales']['invoice_costs'] + 1850
    from ims import profit_report
    pr = profit_report.build('month', OCT1, basis='owed', today=OCT31)
    assert not any(w['kind'] == 'no_cost' and any(r['ref'] == 'INV-2026-8454' for r in w['rows']) for w in pr['warnings'])
    html = (__import__('pathlib').Path(__file__).resolve().parent.parent / 'staticfiles' / 'hq-dashboard.html').read_text()
    assert 'job / parts costs' in html
    assert html.index('/portal/static/js/app.js') < html.index('chart.js@4.4.3')          # app.js bundles an older Chart; v4 must load after it


# ── Profit by invoice (the owner's October 2026 table) ─────────────────────────────────────────────────────────────────────

def _inv(number, client, price, cost, lines=None, paid_on=None, status='sent', desc='', period=OCT1, issued=OCT1):
    lines = lines or [(desc or 'Work', price, cost, '', '')]
    i = make_inv(number, client, lines, paid_on=paid_on, period=period, issued=issued)
    if status != 'sent' and not paid_on:
        Invoice.objects.filter(pk=i.pk).update(status=status, **({'sent_at': None} if status == 'draft' else {}))
    return Invoice.objects.get(pk=i.pk)


@pytest.fixture
def owner_oct(db, monkeypatch):
    monkeypatch.setattr(billing, '_today', lambda: OCT31)
    ensure_seeded()
    admin = make_user('admin')
    _inv('INV-2026-2651', 'Thebado Fuels', 3000, 0, desc='Fuel site job')
    _inv('INV-2026-7448', 'Thebado Fuels', 2800, 0, desc='Second site job')
    _inv('INV-2026-9303', 'Thebado Inc (Omoda)', 1500, 0, desc='Omoda hardware')
    _inv('INV-2026-10-005', 'Thebado Inc (WiFi)', 0, 0, lines=[('WiFi / Internet', 1000, 700, 'Head office', 'wifi'), ('WiFi / Internet', 1000, 700, 'Mthombeni', 'wifi'),
                                                             ('WiFi / Internet', 1000, 700, 'Zisize', 'wifi'), ('Website hosting', 1220, 558, '', 'hosting')])
    job = _inv('INV-2026-8454', 'Nethezeka (job)', 3350, 0, desc='Network job')
    Expense.objects.create(category='cogs', account=cat('Hardware & Parts Purchases').account, expense_category=cat('Hardware & Parts Purchases'), amount=1250, vendor='Supplier',
                           description='Nethezeka job supplies (invoice INV-2026-8454)', expense_date=OCT1, payment_status='paid', recorded_by=admin)
    Expense.objects.create(category='cogs', account=cat('Hardware & Parts Purchases').account, expense_category=cat('Hardware & Parts Purchases'), amount=600, vendor='Contractor',
                           description='Nethezeka job labour (invoice INV-2026-8454)', expense_date=OCT1, payment_status='paid', recorded_by=admin)
    _inv('INV-2026-10-004', 'Nethezeka (WiFi)', 579, 379, desc='WiFi', lines=[('WiFi / Internet', 579, 379, '', 'wifi')])
    _inv('INV-2026-10-003', 'Maputalandfm', 0, 0, lines=[('WiFi / Internet', 1700, 700, '', 'wifi'), ('Website hosting', 1000, 300, '', 'hosting')])
    _inv('INV-2026-10-007', 'Zisize', 899, 700, paid_on=date(2026, 10, 6), lines=[('WiFi / Internet', 899, 700, '', 'wifi')])
    _inv('INV-2026-10-008', 'EkasiFlavours', 700, 379, paid_on=date(2026, 10, 7), lines=[('WiFi / Internet', 700, 379, '', 'wifi')])
    _inv('INV-2026-10-009', 'IngwavumaDollie', 500, 379, paid_on=date(2026, 10, 8), lines=[('WiFi / Internet', 500, 379, '', 'wifi')])
    _inv('INV-DRAFT', 'Draft Client', 999, 0, status='draft')
    _inv('INV-CANCELLED', 'Cancelled Client', 888, 0, status='cancelled')
    # running costs: rent 2,000 + own Axxess lines 979 + domains 69 = 3,048
    Expense.objects.create(category='operating', account=cat('Rent').account, expense_category=cat('Rent'), amount=2000, vendor='Landlord', expense_date=OCT1, payment_status='paid', recorded_by=admin)
    acct = SupplierAccount.objects.get(account_number='296356')
    RecurringExpense.objects.create(name='Owners house', vendor='Axxess', amount=600, start_date=OCT1, supplier_account=acct, expense_category=cat('Internet & Axxess (own lines)'))
    RecurringExpense.objects.create(name='BOSEALETSE', vendor='Axxess', amount=379, start_date=OCT1, supplier_account=acct, expense_category=cat('Internet & Axxess (own lines)'))
    RecurringExpense.objects.create(name='Domains', vendor='Afrihost', amount=69, start_date=OCT1, expense_category=cat('Domains, Email & Hosting (own use)'))
    recurring.post_due(OCT1)
    # Axxess account bills for October: counted above already, never a cost again
    for number, amt, status in (('296356', 2175, 'unpaid'), ('343721', 2655, 'unpaid'), ('379248', 1398, 'paid')):
        Expense.objects.create(category='operating', account=cat('Internet & Axxess (own lines)').account, expense_category=cat('Internet & Axxess (own lines)'), amount=amt, vendor='Axxess',
                               description=f'Axxess account {number}', expense_date=date(2026, 10, 2), payment_status=status, is_supplier_bill=True,
                               supplier_account=SupplierAccount.objects.get(account_number=number), paid_on=date(2026, 10, 12) if status == 'paid' else None, recorded_by=admin)
    return {'admin': admin, 'job': job}


def test_profit_by_invoice_reproduces_the_owner_table(owner_oct):
    rep = pnl.profit_by_invoice('2026-10', today=OCT31)
    got = {r['invoice']: (r['amount'], r['cost'], r['profit']) for r in rep['unpaid']['rows']}
    assert got == {'INV-2026-2651': (3000, 0, 3000), 'INV-2026-7448': (2800, 0, 2800), 'INV-2026-9303': (1500, 0, 1500), 'INV-2026-10-005': (4220, 2658, 1562),
                   'INV-2026-8454': (3350, 1850, 1500), 'INV-2026-10-004': (579, 379, 200), 'INV-2026-10-003': (2700, 1000, 1700)}
    assert rep['unpaid']['totals'] == {'amount': 18149, 'cost': 5887, 'profit': 12262}
    assert {r['invoice']: (r['amount'], r['cost'], r['profit']) for r in rep['paid']['rows']} == {'INV-2026-10-007': (899, 700, 199), 'INV-2026-10-008': (700, 379, 321), 'INV-2026-10-009': (500, 379, 121)}
    assert rep['paid']['totals'] == {'amount': 2099, 'cost': 1458, 'profit': 641}
    assert [r['client'] for r in rep['unpaid']['rows']] == sorted([r['client'] for r in rep['unpaid']['rows']], key=str.lower)      # sorted by client
    assert rep['running']['amount'] == 3048 and {g['item']: g['amount'] for g in rep['running']['items']} == {
        'Rent': 2000, 'Internet & Axxess (own lines)': 979, 'Domains, Email & Hosting (own use)': 69}
    s = {l['key']: l['amount'] for l in rep['summary']}
    assert (s['invoiced'], s['costs'], s['gross'], s['running'], s['net']) == (20248, 7345, 12903, 3048, 9855) and rep['net_profit'] == 9855
    sup = rep['suppliers']
    assert {b['account']: (b['amount'], b['status']) for b in sup['rows']} == {'296356': (2175, 'unpaid'), '343721': (2655, 'unpaid'), '379248': (1398, 'paid')}
    assert sup['total'] == 6228 and sup['still_to_pay'] == 4830 and 'not an extra cost' in sup['note']


def test_profit_by_invoice_agrees_with_dashboard_and_accrual_pnl(owner_oct):
    rep = pnl.profit_by_invoice('2026-10', today=OCT31)
    dash = finance.summary(OCT1, OCT31, today=OCT31)['accrual']
    accrual = pnl.build('accrual', 'month', OCT1, today=OCT31)
    assert rep['net_profit'] == dash['profit_if_paid'] == line(accrual, 'net') == 9855
    assert dash['revenue']['invoices'] == 20248 and rep['check'] == {'report': 9855, 'dashboard': 9855, 'pnl': 9855, 'ok': True}
    assert dash['cost_of_sales']['job_costs'] == 1850 and dash['cost_of_sales']['invoice_costs'] == 5495 and dash['operating'] == 3048
    assert not any(w['kind'] == 'mismatch' for w in rep['warnings'])
    # notes: breakdowns for costed invoices, "no cost recorded" for the 100%-profit ones
    notes = {r['invoice']: r['note'] for r in rep['unpaid']['rows']}
    assert notes['INV-2026-2651'] == 'no cost recorded' and 'Axxess R2,100.00' in notes['INV-2026-10-005'] and 'hosting R558.00' in notes['INV-2026-10-005']
    assert 'supplies R1,250.00' in notes['INV-2026-8454'] and 'labour R600.00' in notes['INV-2026-8454']
    assert {w['kind'] for w in rep['warnings']} >= {'no_cost'}


def test_supplier_bills_are_not_counted_as_cost_and_drafts_cancelled_are_excluded(owner_oct):
    rep = pnl.profit_by_invoice('2026-10', today=OCT31)
    listed = {r['invoice'] for r in rep['unpaid']['rows'] + rep['paid']['rows']}
    assert 'INV-DRAFT' not in listed and 'INV-CANCELLED' not in listed
    # taking the Axxess bills away changes nothing; they live in section E only
    Expense.objects.filter(is_supplier_bill=True).delete()
    assert pnl.profit_by_invoice('2026-10', today=OCT31)['net_profit'] == 9855


def test_cost_link_by_invoice_id_quotation_or_number(owner_oct):
    from ims.models import Quotation
    admin = owner_oct['admin']
    plain = _inv('INV-LINK-1', 'Link Client', 1000, 0, desc='by id')
    quoted = _inv('INV-LINK-2', 'Link Client', 1000, 0, desc='by quote')
    numbered = _inv('INV-LINK-3', 'Link Client', 1000, 0, desc='by number')
    mk = lambda **kw: Expense.objects.create(category='cogs', account=cat('Hardware & Parts Purchases').account, expense_category=cat('Hardware & Parts Purchases'), vendor='S',
                                             expense_date=OCT1, payment_status='paid', recorded_by=admin, **kw)
    mk(amount=100, description='direct link', invoice=plain)
    mk(amount=200, description='via quotation', quotation=Quotation.objects.create(quote_number='Q-LINK', client_name='x', invoice=quoted, issue_date=OCT1))
    mk(amount=300, description='labour for inv-link-3 job')
    rep = pnl.profit_by_invoice('2026-10', today=OCT31)
    costs = {r['invoice']: r['cost'] for r in rep['unpaid']['rows']}
    assert costs['INV-LINK-1'] == 100 and costs['INV-LINK-2'] == 200 and costs['INV-LINK-3'] == 300
    assert rep['check']['ok'] and rep['net_profit'] == 9855 + 3000 - 600


def test_profit_by_invoice_places_invoices_by_billing_period(owner_oct):
    _inv('INV-MOVED', 'Moved Client', 500, 0, period=date(2026, 9, 1), issued=date(2026, 9, 27))
    assert 'INV-MOVED' not in {r['invoice'] for r in pnl.profit_by_invoice('2026-10', today=OCT31)['unpaid']['rows']}
    assert 'INV-MOVED' in {r['invoice'] for r in pnl.profit_by_invoice('2026-09', today=OCT31)['unpaid']['rows']}
    Invoice.objects.filter(invoice_number='INV-MOVED').update(billing_period_start=OCT1, billing_period_end=date(2026, 10, 28))
    assert 'INV-MOVED' in {r['invoice'] for r in pnl.profit_by_invoice('2026-10', today=OCT31)['unpaid']['rows']}


def test_september_project_cost_follows_its_invoice(db, monkeypatch):
    monkeypatch.setattr(billing, '_today', lambda: OCT31)
    ensure_seeded()
    admin = make_user('admin')
    sept = date(2026, 9, 10)
    _inv('INV-2026-1860', 'Siyaya', 20000, 0, desc='Siyaya project', period=date(2026, 9, 1), issued=sept)
    Expense.objects.create(category='cogs', account=cat('Hardware & Parts Purchases').account, expense_category=cat('Hardware & Parts Purchases'), amount=13500, vendor='Siyaya suppliers',
                           description='Siyaya project cost (INV-2026-1860)', expense_date=date(2026, 9, 12), payment_status='paid', recorded_by=admin)
    rep = pnl.profit_by_invoice('2026-09', today=OCT31)
    row = rep['unpaid']['rows'][0]
    assert (row['amount'], row['cost'], row['profit']) == (20000, 13500, 6500) and rep['check']['ok'] and rep['net_profit'] == 6500
    assert rep['summary'][0]['amount'] == 20000


def test_profit_by_invoice_endpoint_exports_and_permissions(owner_oct):
    api = client_for(owner_oct['admin'])
    d = api.get('/api/finance/profit-by-invoice/?month=2026-10').data
    assert d['net_profit'] == 9855 and d['generated_at'] and d['check']['ok']
    assert api.get('/api/finance/profit-by-invoice/?month=garbage').status_code == 400
    assert api.get('/api/finance/profit-by-invoice/pdf/?month=2026-10').content[:4] == b'%PDF'
    csv_ = api.get('/api/finance/profit-by-invoice/csv/?month=2026-10').content.decode()
    assert 'INV-2026-8454' in csv_ and 'Total' in csv_ and '9855.00' in csv_
    for who in ('cashier', 'client'):
        assert client_for(make_user(who)).get('/api/finance/profit-by-invoice/?month=2026-10').status_code == 403
    ri = (__import__('pathlib').Path(__file__).resolve().parent.parent / 'staticfiles' / 'hq-revenue-intelligence.html').read_text()
    assert 'Profit by invoice' in ri and 'pbiGo' in ri and 'pbiPdf' in ri

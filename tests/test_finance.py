from datetime import date, timedelta
from decimal import Decimal

import pytest

from ims import finance
from ims.ledger import ensure_seeded, post_payroll_entry
from ims.models import (
    Account, CashTransaction, CompliancePeriod, Employee, Expense, ExpenseCategory, Invoice,
    LedgerTransaction, PayrollEntry, Quotation,
)
from tests.conftest import client_for, make_user

TODAY = date(2026, 9, 15)   # a Tuesday


def invoice(number, subtotal, status, paid_on=None, sent_on=TODAY, inv_type='adhoc', vat=15, wholesale=None, due=None):
    sub = Decimal(str(subtotal))
    tax = (sub * Decimal(vat) / 100).quantize(Decimal('0.01'))
    inv = Invoice.objects.create(
        invoice_number=number, billing_period_start=sent_on, billing_period_end=sent_on,
        subtotal=sub, tax_rate=vat, tax_amount=tax, total_amount=sub + tax, ticket_count=0, hours_worked=0,
        status='draft', invoice_type=inv_type, wholesale_cost=wholesale, due_date=due,
    )
    # set the dates explicitly (save() would otherwise stamp "now")
    from django.utils import timezone
    Invoice.objects.filter(pk=inv.pk).update(
        status=status, sent_at=timezone.make_aware(__import__('datetime').datetime.combine(sent_on, __import__('datetime').time(10))),
        payment_date=paid_on)
    return Invoice.objects.get(pk=inv.pk)


@pytest.fixture
def world(db, admin):
    ensure_seeded()
    cat_rent = ExpenseCategory.objects.get(name='Rent')
    cat_parts = ExpenseCategory.objects.get(name='Hardware & Parts Purchases')
    cat_tools = ExpenseCategory.objects.get(name='Equipment & Tools')
    # paid in Sept: 1000 + 2000 (ex VAT) ; wifi with wholesale 400
    invoice('INV-1', 1000, 'paid', paid_on=date(2026, 9, 10))
    invoice('INV-2', 2000, 'paid', paid_on=date(2026, 9, 12), inv_type='wifi', wholesale=400)
    # paid in August (different month)
    invoice('INV-3', 500, 'paid', paid_on=date(2026, 8, 20), sent_on=date(2026, 8, 1))
    # unpaid (sent) one overdue by due date
    invoice('INV-4', 800, 'sent', sent_on=date(2026, 9, 5), due=date(2026, 9, 10))
    invoice('INV-5', 100, 'overdue', sent_on=date(2026, 8, 25))
    invoice('INV-6', 999, 'draft')       # drafts never count
    invoice('INV-7', 999, 'cancelled')   # nor cancelled
    CashTransaction.objects.create(amount=300, payment_method='cash', description='Retail sale', performed_by=admin)
    # linked-to-invoice payments must NOT be double counted
    CashTransaction.objects.create(amount=1000, payment_method='eft', description='pay INV-1', performed_by=admin,
                                   invoice=Invoice.objects.get(invoice_number='INV-1'))
    Expense.objects.create(category='operating', account=cat_rent.account, expense_category=cat_rent, amount=600,
                           vendor='Landlord', expense_date=date(2026, 9, 1), payment_status='paid', recorded_by=admin)
    Expense.objects.create(category='cogs', account=cat_parts.account, expense_category=cat_parts, amount=250,
                           vendor='Parts Co', expense_date=date(2026, 9, 3), payment_status='unpaid', recorded_by=admin)
    Expense.objects.create(category='capital', account=cat_tools.account, expense_category=cat_tools, amount=5000,
                           vendor='Tool shop', expense_date=date(2026, 9, 4), payment_status='paid', recorded_by=admin)
    # approved payroll for September, draft payroll must be ignored
    period = CompliancePeriod.objects.create(period_label='2026-09', period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))
    e1 = Employee.objects.create(employee_number='E1', first_name='A', last_name='B', gross_monthly_salary=10000)
    e2 = Employee.objects.create(employee_number='E2', first_name='C', last_name='D', gross_monthly_salary=8000)
    PayrollEntry.objects.create(employee=e1, compliance_period=period, gross_salary=10000, total_gross=10000,
                                paye_amount=0, uif_employee=100, uif_employer=100, net_pay=9900, is_frozen=True)
    PayrollEntry.objects.create(employee=e2, compliance_period=period, gross_salary=8000, total_gross=8000,
                                paye_amount=0, uif_employee=80, uif_employer=80, net_pay=7920, is_frozen=False)
    return None


def test_summary_numbers_and_workings_agree(world):
    s = finance.summary(date(2026, 9, 1), date(2026, 9, 30), today=date(2026, 9, 30))
    # Paid invoices are counted ex VAT by payment date; August one excluded
    assert s['invoices']['paid']['count'] == 2
    assert s['invoices']['paid']['subtotal'] == 3000
    assert s['invoices']['paid']['vat'] == 450
    assert s['invoices']['paid']['total'] == 3450
    # Unpaid = sent + overdue issued up to period end (drafts/cancelled excluded), VAT inclusive (what is owed to us)
    assert s['invoices']['unpaid']['count'] == 2
    assert s['invoices']['unpaid']['total'] == pytest.approx(800 * 1.15 + 100 * 1.15)
    assert s['invoices']['unpaid']['overdue_count'] == 2          # INV-4 past due date, INV-5 marked overdue
    # Revenue = paid (ex VAT) + direct sale; the invoice-linked cash payment is NOT added again
    assert s['revenue'] == {'invoices': 3000.0, 'direct_sales': 300.0, 'total': 3300.0}
    # Expenses: axxess 400 + cogs 250 + opex 600 + payroll (approved only: 10000 + 100 employer UIF)
    assert s['expenses']['axxess'] == 400
    assert s['expenses']['cogs'] == 250
    assert s['expenses']['operating'] == 600
    assert s['expenses']['payroll'] == 10100
    assert s['expenses']['total'] == 400 + 250 + 600 + 10100
    assert s['expenses']['capital_purchases'] == 5000            # shown, but not deducted
    assert s['expenses']['unpaid_to_suppliers'] == 250
    assert s['profit']['net'] == 3300 - 11350
    assert s['profit']['gross'] == 3300 - 650
    # the workings walk to the same answer
    steps = {w['key']: w for w in s['workings']}
    assert steps['revenue']['amount'] == s['revenue']['total']
    assert steps['net_profit']['amount'] == s['profit']['net']
    assert steps['paid_invoices']['rows'] and steps['paid_invoices']['rows'][0]['ref'] in ('INV-1', 'INV-2')
    calc = (steps['paid_invoices']['amount'] + steps['direct_sales']['amount'] - steps['axxess']['amount']
            - steps['cogs']['amount'] - steps['opex']['amount'] - steps['payroll']['amount'])
    assert calc == pytest.approx(s['profit']['net'])


def test_week_month_year_are_consistent(world):
    week = finance.resolve_period('week', date(2026, 9, 10))
    assert week[0] == date(2026, 9, 7) and week[1] == date(2026, 9, 13)
    s_week = finance.summary(week[0], week[1], today=date(2026, 9, 30))
    assert s_week['invoices']['paid']['subtotal'] == 3000        # both paid on the 10th and 12th
    s_year = finance.summary(date(2026, 1, 1), date(2026, 12, 31), today=date(2026, 9, 30))
    assert s_year['invoices']['paid']['subtotal'] == 3500        # + the August invoice


@pytest.mark.parametrize('gran,n', [('weekly', 12), ('monthly', 12), ('yearly', 5)])
def test_trend_bucket_counts(world, gran, n):
    t = finance.trend(gran, today=date(2026, 9, 30))
    assert len(t['buckets']) == n


def test_trend_totals_match_summary(world):
    t = finance.trend('monthly', periods=2, today=date(2026, 9, 30))
    sept = t['buckets'][-1]
    s = finance.summary(date(2026, 9, 1), date(2026, 9, 30), today=date(2026, 9, 30))
    assert sept['label'] == 'Sep 2026'
    assert sept['revenue'] == s['revenue']['total']
    assert sept['expenses'] == s['expenses']['total']
    assert sept['profit'] == s['profit']['net']
    aug = t['buckets'][0]
    assert aug['revenue'] == 500
    y = finance.trend('yearly', periods=1, today=date(2026, 9, 30))['buckets'][0]
    assert y['revenue'] == 3800   # 3000 + 500 + 300 direct


def test_trend_week_buckets_start_on_monday(world):
    t = finance.trend('weekly', periods=3, today=date(2026, 9, 15))
    assert [b['start'] for b in t['buckets']] == ['2026-08-31', '2026-09-07', '2026-09-14']
    assert t['buckets'][1]['revenue'] == 3000


def test_invalid_granularity():
    with pytest.raises(ValueError):
        finance.trend('daily')


def test_invoice_save_stamps_dates(db):
    inv = Invoice.objects.create(
        invoice_number='X1', billing_period_start=TODAY, billing_period_end=TODAY, subtotal=10, total_amount=10,
        ticket_count=0, hours_worked=0, status='sent')
    assert inv.sent_at is not None and inv.payment_date is None
    inv.status = 'paid'
    inv.save(update_fields=['status'])          # the way cashier / PayFast do it
    inv.refresh_from_db()
    assert inv.payment_date is not None


# ── API ──────────────────────────────────────────────────────────────────────

def test_summary_api_permissions(world, cashier):
    assert client_for(cashier).get('/api/finance/summary/').status_code == 403
    r = client_for(make_user('finance')).get('/api/finance/summary/?period=year&date=2026-09-15')
    assert r.status_code == 200 and r.data['period']['label'] == '2026'


def test_summary_api_custom_period_validation(world, api):
    assert api.get('/api/finance/summary/?period=custom').status_code == 400
    r = api.get('/api/finance/summary/?period=custom&date_from=2026-09-01&date_to=2026-09-30')
    assert r.status_code == 200 and r.data['revenue']['total'] == 3300


def test_trend_api(world, api):
    r = api.get('/api/finance/trend/?granularity=weekly&periods=4')
    assert r.status_code == 200 and len(r.data['buckets']) == 4
    assert api.get('/api/finance/trend/?granularity=hourly').status_code == 400


def test_expense_category_drives_account_and_stream(db, api):
    cats = api.get('/api/expense-categories/').data
    assert {c['name'] for c in cats} >= {'Rent', 'Equipment & Tools'}
    tools = next(c for c in cats if c['name'] == 'Equipment & Tools')
    r = api.post('/api/expenses/', {'expense_category': tools['id'], 'amount': '1200', 'vendor': 'Tool shop',
                                   'expense_date': '2026-09-02'}, format='json')
    assert r.status_code == 201
    e = Expense.objects.get(pk=r.data['id'])
    assert e.category == 'capital' and e.cash_flow_stream == 'icf' and e.account.system_key == 'FIXED_ASSETS'
    assert LedgerTransaction.objects.filter(source_model='Expense', source_id=str(e.id)).exists()


def test_expense_validation(db, api):
    cats = api.get('/api/expense-categories/').data
    base = {'expense_category': cats[0]['id'], 'vendor': 'X', 'expense_date': '2026-09-02'}
    assert api.post('/api/expenses/', {**base, 'amount': '-5'}, format='json').status_code == 400
    assert api.post('/api/expenses/', {**base, 'amount': 'abc'}, format='json').status_code == 400
    assert api.post('/api/expenses/', {**base, 'amount': '5', 'expense_category': 'nope'}, format='json').status_code == 400


def test_category_crud_and_rules(db, api):
    ensure_seeded()
    opex = Account.objects.get(system_key='OPEX_OTHER')
    asset = Account.objects.get(system_key='FIXED_ASSETS')
    r = api.post('/api/expense-categories/', {'name': 'Staff Training', 'kind': 'operating', 'account': str(opex.id),
                                              'monthly_budget': '500'}, format='json')
    assert r.status_code == 201
    # wrong account type for the kind
    assert api.post('/api/expense-categories/', {'name': 'Bad', 'kind': 'operating', 'account': str(asset.id)}, format='json').status_code == 400
    # duplicate name
    assert api.post('/api/expense-categories/', {'name': 'staff training', 'kind': 'operating', 'account': str(opex.id)}, format='json').status_code == 400
    cid = r.data['id']
    api.post('/api/expenses/', {'expense_category': cid, 'amount': '100', 'vendor': 'Trainer', 'expense_date': date.today().isoformat()}, format='json')
    row = next(c for c in api.get('/api/expense-categories/').data if c['id'] == cid)
    assert row['spent_this_month'] == 100 and row['monthly_budget'] == 500
    # has history -> deactivated not deleted
    d = api.delete(f'/api/expense-categories/{cid}/')
    assert d.status_code == 200 and d.data['deactivated']


def test_expense_delete_reverses_ledger_and_mark_paid(db, api):
    cats = api.get('/api/expense-categories/').data
    rent = next(c for c in cats if c['name'] == 'Rent')
    r = api.post('/api/expenses/', {'expense_category': rent['id'], 'amount': '700', 'vendor': 'Landlord',
                                   'expense_date': '2026-09-01', 'payment_status': 'unpaid'}, format='json')
    eid = r.data['id']
    assert api.patch(f'/api/expenses/{eid}/', {'amount': '1'}, format='json').status_code == 400   # locked
    p = api.patch(f'/api/expenses/{eid}/', {'payment_status': 'paid'}, format='json')
    assert p.status_code == 200
    assert LedgerTransaction.objects.filter(source_model='ExpensePayment', source_id=eid).exists()
    assert api.delete(f'/api/expenses/{eid}/').status_code == 204
    # every posting is mirrored by a reversal, so the account nets to zero
    from django.db.models import Sum
    from ims.models import LedgerEntry
    for acct in Account.objects.all():
        agg = LedgerEntry.objects.filter(account=acct).aggregate(d=Sum('debit'), c=Sum('credit'))
        assert (agg['d'] or 0) == (agg['c'] or 0)


# ── Quotations ───────────────────────────────────────────────────────────────

def test_quotation_lifecycle_links_expenses(db, api):
    cats = api.get('/api/expense-categories/').data
    parts = next(c for c in cats if c['name'] == 'Hardware & Parts Purchases')
    r = api.post('/api/quotations/', {
        'client_name': 'Acme', 'title': 'Office network', 'vat_rate': 15,
        'items': [
            {'description': 'Switch install', 'quantity': 2, 'unit_price': 500, 'unit_cost': 200, 'cost_category': parts['id']},
            {'description': 'Labour', 'quantity': 4, 'unit_price': 250, 'unit_cost': 100},
        ]}, format='json')
    assert r.status_code == 201, r.data
    q = r.data
    assert q['subtotal'] == 2000 and q['tax_amount'] == 300 and q['total_amount'] == 2300
    assert q['estimated_cost'] == 800 and q['expected_margin'] == 1200
    assert q['quote_number'].startswith(f'Q-{date.today().year}-')
    qid = q['id']

    # cannot convert before acceptance
    assert api.post(f'/api/quotations/{qid}/action/', {'action': 'convert'}, format='json').status_code == 400
    assert api.post(f'/api/quotations/{qid}/action/', {'action': 'send'}, format='json').data['status'] == 'sent'
    assert api.post(f'/api/quotations/{qid}/action/', {'action': 'accept'}, format='json').data['status'] == 'accepted'
    # edits locked after acceptance
    assert api.patch(f'/api/quotations/{qid}/', {'title': 'x'}, format='json').status_code == 400

    # an expense tagged to the quote shows up as actual cost
    api.post('/api/expenses/', {'expense_category': parts['id'], 'amount': '900', 'vendor': 'Supplier',
                                'expense_date': '2026-09-02', 'quotation': qid}, format='json')
    d = api.get(f'/api/quotations/{qid}/').data
    assert d['actual_cost'] == 900 and d['cost_variance'] == 100 and d['actual_margin'] == 1100
    assert d['expenses'][0]['vendor'] == 'Supplier'

    c = api.post(f'/api/quotations/{qid}/action/', {'action': 'convert'}, format='json')
    assert c.status_code == 200 and c.data['status'] == 'invoiced' and c.data['invoice_number']
    inv = Invoice.objects.get(invoice_number=c.data['invoice_number'])
    assert inv.subtotal == 2000 and inv.total_amount == 2300 and inv.items.count() == 2 and inv.status == 'draft'
    assert api.post(f'/api/quotations/{qid}/action/', {'action': 'convert'}, format='json').status_code == 400


def test_quotation_validation_and_permissions(db, api, cashier):
    assert api.post('/api/quotations/', {'client_name': '', 'items': []}, format='json').status_code == 400
    bad = api.post('/api/quotations/', {'client_name': 'A', 'items': [{'description': 'x', 'quantity': 0, 'unit_price': 5}]}, format='json')
    assert bad.status_code == 400
    assert Quotation.objects.count() == 0            # rolled back
    assert client_for(cashier).get('/api/quotations/').status_code == 403
    r = api.post('/api/quotations/', {'client_name': 'A', 'items': [{'description': 'x', 'quantity': 1, 'unit_price': 10}]}, format='json')
    assert api.delete(f"/api/quotations/{r.data['id']}/").status_code == 204


def test_expired_quotes_are_marked(db, api):
    r = api.post('/api/quotations/', {'client_name': 'A', 'valid_until': (date.today() - timedelta(days=1)).isoformat(),
                                      'items': [{'description': 'x', 'quantity': 1, 'unit_price': 10}]}, format='json')
    lst = api.get('/api/quotations/').data
    assert lst['results'][0]['status'] == 'expired'


# ── HR / payroll API ─────────────────────────────────────────────────────────

def test_hr_data_is_restricted(db, cashier, api):
    c = client_for(cashier)
    for url in ('/api/employees/', '/api/payroll/', '/api/leave-requests/', '/api/compliance/'):
        assert c.get(url).status_code == 403, url
    assert api.get('/api/employees/').status_code == 200


def test_employee_validation_and_payroll_run(db, api):
    bad = api.post('/api/employees/', {'first_name': 'A', 'last_name': 'B', 'gross_monthly_salary': 10000, 'id_number': '123'}, format='json')
    assert bad.status_code == 400
    assert api.post('/api/employees/', {'first_name': 'A', 'last_name': 'B', 'gross_monthly_salary': -1}, format='json').status_code == 400
    ok = api.post('/api/employees/', {'first_name': 'Ann', 'last_name': 'Nel', 'gross_monthly_salary': 30000,
                                      'monthly_allowance': 500, 'monthly_other_deduction': 200}, format='json')
    assert ok.status_code == 201
    eid = __import__('ims.models', fromlist=['Employee']).Employee.objects.get(employee_number=ok.data['employee_number']).id

    run = api.post('/api/payroll/', {'month': '2026-09', 'adjustments': {str(eid): {'overtime_hours': 5}}}, format='json')
    assert run.status_code == 200 and run.data['created'] == 1
    rows = api.get('/api/payroll/?month=2026-09').data
    row = rows['rows'][0]
    assert row['status'] == 'draft' and row['allowances'] == 500 and row['overtime_amount'] > 0
    assert row['uif_employee'] == 177.12
    assert row['net_pay'] == pytest.approx(row['gross'] - row['paye'] - row['uif_employee'] - 200, abs=0.01)
    # draft payroll is NOT a cost yet
    assert finance.summary(date(2026, 9, 1), date(2026, 9, 30))['expenses']['payroll'] == 0
    # cannot mark paid before approval
    assert api.patch(f"/api/payroll/{row['id']}/", {'action': 'paid'}, format='json').status_code == 400
    assert api.patch(f"/api/payroll/{row['id']}/", {'action': 'approve'}, format='json').status_code == 200
    # ledger balances even with deductions + employer UIF
    from django.db.models import Sum
    from ims.models import LedgerEntry
    agg = LedgerEntry.objects.aggregate(d=Sum('debit'), c=Sum('credit'))
    assert agg['d'] == agg['c'] and agg['d'] > 0
    # approved payroll is now a cost and is never overwritten by a recalculation
    assert finance.summary(date(2026, 9, 1), date(2026, 9, 30))['expenses']['payroll'] == pytest.approx(row['employer_cost'])
    again = api.post('/api/payroll/', {'month': '2026-09'}, format='json')
    assert again.data['skipped_approved'] == 1
    assert api.patch(f"/api/payroll/{row['id']}/", {'action': 'paid', 'paid_on': '2026-09-30'}, format='json').status_code == 200
    slip = api.get(f"/api/payroll/{row['id']}/").data
    assert slip['status'] == 'paid' and slip['period'] == '2026-09'


def test_leave_cannot_be_approved_twice(db, api):
    e = api.post('/api/employees/', {'first_name': 'A', 'last_name': 'B', 'gross_monthly_salary': 5000}, format='json').data
    lr = api.post('/api/leave-requests/', {'employee_id': e['id'], 'leave_type': 'annual', 'start_date': '2026-10-01',
                                           'end_date': '2026-10-02', 'days_requested': 2}, format='json').data
    assert api.patch(f"/api/leave-requests/{lr['id']}/", {'action': 'approve'}, format='json').status_code == 200
    assert api.patch(f"/api/leave-requests/{lr['id']}/", {'action': 'approve'}, format='json').status_code == 400


# ── Quotation PDF ────────────────────────────────────────────────────────────

def _make_quote(api, **kw):
    body = {'client_name': 'Acme <Traders> & Sons', 'title': 'Shop network', 'vat_rate': 15, 'notes': 'Thanks!\nSecond line',
            'items': [{'description': 'Switch install', 'quantity': 2, 'unit_price': 500, 'unit_cost': 321.5},
                      {'description': 'Labour', 'quantity': 4.5, 'unit_price': 250, 'unit_cost': 99}]}
    body.update(kw)
    return api.post('/api/quotations/', body, format='json').data


def test_quote_pdf_endpoint(db, api, cashier):
    q = _make_quote(api)
    r = api.get(f"/api/quotations/{q['id']}/pdf/")
    assert r.status_code == 200 and r['Content-Type'] == 'application/pdf'
    assert r.content.startswith(b'%PDF') and b'inline' in r['Content-Disposition'].encode() and q['quote_number'] in r['Content-Disposition']
    d = api.get(f"/api/quotations/{q['id']}/pdf/?download=1")
    assert 'attachment' in d['Content-Disposition']
    assert client_for(cashier).get(f"/api/quotations/{q['id']}/pdf/").status_code == 403
    import uuid
    assert api.get(f"/api/quotations/{uuid.uuid4()}/pdf/").status_code == 404


def test_quote_pdf_content_is_client_safe(db, api):
    from ims.quote_pdf import build_quote_pdf
    from ims.views import _company_settings
    q = Quotation.objects.get(pk=_make_quote(api)['id'])
    cs = _company_settings(); cs.account_number = '123456789'; cs.vat_number = '4455667788'; cs.save()
    pdf = build_quote_pdf(q, cs, compress=False)
    text = pdf.decode('latin-1')
    for must in (q.quote_number, 'QUOTATION', 'Switch install', 'Labour', '(Acme <)', '(Traders)', '(> & Sons)',
                 'R 1 000.00', 'R 1 125.00', 'R 2 125.00', 'R 318.75', 'R 2 443.75', '123456789', 'ACCEPTANCE', 'DRAFT'):
        assert must in text, must
    assert '&lt;' not in text and '&amp;' not in text     # user text is escaped, not leaked as entities
    # internal costs / margin must never appear
    for secret in ('321.50', '99.00', 'margin', 'Margin', 'estimated', 'Expected'):
        assert secret not in text, secret


def test_quote_pdf_many_lines_and_status_stamp(db, api):
    from ims.quote_pdf import build_quote_pdf
    from ims.views import _company_settings
    items = [{'description': f'Line {i} ' + 'long description ' * 8, 'quantity': 1, 'unit_price': 10 + i} for i in range(60)]
    q = Quotation.objects.get(pk=_make_quote(api, items=items)['id'])
    Quotation.objects.filter(pk=q.pk).update(status='accepted')
    q.refresh_from_db()
    pdf = build_quote_pdf(q, _company_settings(), compress=False)
    assert pdf.count(b'/Type /Page\n') >= 2 or pdf.count(b'/Type /Page ') >= 2 or pdf.count(b'/Page') >= 3
    assert b'DRAFT' not in pdf     # accepted quotes carry no draft stamp


def test_quote_email_attaches_pdf(db, api):
    from django.core import mail
    q = _make_quote(api, client_email='client@example.com')
    r = api.post(f"/api/quotations/{q['id']}/action/", {'action': 'send', 'email': True}, format='json')
    assert r.data['emailed'] is True
    assert mail.outbox[-1].attachments[0][0] == f"{q['quote_number']}.pdf"
    assert mail.outbox[-1].attachments[0][1].startswith(b'%PDF')

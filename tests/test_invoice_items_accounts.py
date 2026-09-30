from decimal import Decimal

import pytest
from django.test import Client

from ims.models import Account, Company, Invoice
from tests.conftest import client_for, make_user


@pytest.fixture
def company(db):
    return Company.objects.create(name='Acme', slug='acme')


def body(company, **kw):
    d = dict(company=str(company.id), invoice_number='INV-T-1', billing_period_start='2026-09-01', billing_period_end='2026-09-30',
             ticket_count=0, hours_worked=0, tax_rate=15, status='draft', description='Network work')
    d.update(kw)
    return d


def test_items_autocalculate_subtotal_vat_total(api, company):
    r = api.post('/api/invoices/', body(company, items=[
        {'description': 'Router', 'quantity': '2', 'unit_price': '499.99'},
        {'description': 'Labour', 'quantity': '3.5', 'unit_price': '250'},
    ]), format='json')
    assert r.status_code == 201, r.data
    assert r.data['subtotal'] == '1874.98'            # 999.98 + 875.00
    assert r.data['tax_amount'] == 281.25 or float(r.data['tax_amount']) == pytest.approx(281.25)
    assert float(r.data['total_amount']) == pytest.approx(2156.23)
    amounts = [i['amount'] for i in r.data['items']]
    assert amounts == ['999.98', '875.00']


def test_editing_items_replaces_and_recalculates(api, company):
    r = api.post('/api/invoices/', body(company, items=[{'description': 'A', 'quantity': 1, 'unit_price': 100}]), format='json')
    iid = r.data['id']
    u = api.patch(f'/api/invoices/{iid}/', {'items': [{'description': 'B', 'quantity': 4, 'unit_price': 25}, {'description': 'C', 'quantity': 1, 'unit_price': 50}]}, format='json')
    assert u.status_code == 200
    assert Invoice.objects.get(pk=iid).items.count() == 2
    assert float(u.data['subtotal']) == 150 and float(u.data['total_amount']) == pytest.approx(172.5)
    # changing only the VAT rate recalculates the total
    t = api.patch(f'/api/invoices/{iid}/', {'tax_rate': 0}, format='json')
    assert float(t.data['total_amount']) == 150


def test_item_validation_and_paid_lock(api, company):
    assert api.post('/api/invoices/', body(company, items=[{'description': 'A', 'quantity': 0, 'unit_price': 10}]), format='json').status_code == 400
    assert api.post('/api/invoices/', body(company, invoice_number='INV-T-2', items=[{'description': 'A', 'quantity': 1, 'unit_price': -1}]), format='json').status_code == 400
    r = api.post('/api/invoices/', body(company, invoice_number='INV-T-3', status='paid', items=[{'description': 'A', 'quantity': 1, 'unit_price': 10}]), format='json')
    assert api.patch(f"/api/invoices/{r.data['id']}/", {'items': [{'description': 'X', 'quantity': 1, 'unit_price': 1}]}, format='json').status_code == 400


def test_invoice_without_items_still_works_and_lists_items(api, company):
    r = api.post('/api/invoices/', body(company, invoice_number='INV-T-4', subtotal='200'), format='json')
    assert r.status_code == 201 and float(r.data['total_amount']) == 230 and r.data['items'] == []
    lst = api.get('/api/invoices/?search=INV-T-4').data
    assert lst['results'][0]['items'] == []


def test_accounts_seed_and_admin_can_add(db, api):
    rows = api.get('/api/accounts/').data            # fresh database: must not be empty
    assert len(rows) >= 20
    r = api.post('/api/accounts/', {'code': '6710', 'name': 'Staff Training', 'account_type': 'expense'}, format='json')
    assert r.status_code == 201
    a = Account.objects.get(code='6710')
    assert a.normal_balance == 'debit' and a.account_subtype == 'operating_expense' and not a.is_system
    assert api.post('/api/accounts/', {'code': '6710', 'name': 'Dup', 'account_type': 'expense'}, format='json').status_code == 400
    assert api.post('/api/accounts/', {'code': '7', 'name': 'X', 'account_type': 'nonsense'}, format='json').status_code == 400
    assert client_for(make_user('finance')).post('/api/accounts/', {'code': '8', 'name': 'X', 'account_type': 'expense'}, format='json').status_code == 403
    # the new account is selectable for a category
    cat = api.post('/api/expense-categories/', {'name': 'Training', 'kind': 'operating', 'account': str(a.id)}, format='json')
    assert cat.status_code == 201


def test_vouchers_are_gone(db, api):
    assert api.get('/api/vouchers/').status_code == 404
    assert Client().get('/dashboard/vouchers/').status_code == 404
    from django.apps import apps
    with pytest.raises(LookupError):
        apps.get_model('ims', 'Voucher')


def test_django_admin_pages_load(db):
    from django.contrib.auth import get_user_model
    su = get_user_model().objects.create_superuser(username='root', email='root@x.co', password='Pw12345!x', role='admin')
    c = Client(); c.force_login(su)
    for url in ('/admin/ims/account/', '/admin/ims/account/add/', '/admin/ims/expensecategory/', '/admin/ims/expensecategory/add/',
                '/admin/ims/expense/', '/admin/ims/quotation/', '/admin/ims/quotation/add/', '/admin/ims/invoice/add/'):
        assert c.get(url).status_code == 200, url

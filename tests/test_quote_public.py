from datetime import date, timedelta

import pytest
from django.core import mail
from django.test import Client

from ims.models import AuditLog, Invoice, Notification, Quotation
from tests.conftest import client_for, make_user


@pytest.fixture
def sent(db, api):
    make_user('finance')   # a second staff member who should also be notified
    q = api.post('/api/quotations/', {'client_name': 'Acme', 'client_email': 'buyer@acme.co', 'vat_rate': 15,
                                      'items': [{'description': 'Install', 'quantity': 2, 'unit_price': 500, 'unit_cost': 321.5}]}, format='json').data
    r = api.post(f"/api/quotations/{q['id']}/action/", {'action': 'send'}, format='json')
    assert r.status_code == 200
    token = r.data['public_url'].rstrip('/').rsplit('/', 1)[1]
    return {'id': q['id'], 'token': token, 'number': q['quote_number'], 'url': r.data['public_url']}


def pub(token, path=''):
    return f'/api/public/quotes/{token}/{path}'


def test_link_created_on_send_not_on_draft(db, api):
    q = api.post('/api/quotations/', {'client_name': 'A', 'items': [{'description': 'x', 'quantity': 1, 'unit_price': 5}]}, format='json').data
    assert q['public_url'] is None
    tok = Quotation.objects.get(pk=q['id'])
    assert tok.public_token is None
    sent = api.post(f"/api/quotations/{q['id']}/action/", {'action': 'send'}, format='json').data
    assert '/quote/' in sent['public_url'] and len(sent['public_url'].rstrip('/').rsplit('/', 1)[1]) >= 30


def test_public_view_is_client_safe_and_counts_views(sent):
    c = Client()
    r = c.get(pub(sent['token']))
    assert r.status_code == 200
    d = r.json()
    assert d['can_respond'] is True and d['status'] == 'sent' and d['total_amount'] == 1150
    text = r.content.decode()
    for secret in ('unit_cost', 'estimated_cost', '321.5', 'margin', 'expenses', 'decision_ip', 'public_token'):
        assert secret not in text, secret
    c.get(pub(sent['token']))
    q = Quotation.objects.get(pk=sent['id'])
    assert q.view_count == 2 and q.first_viewed_at is not None


def test_bad_tokens_are_404(db, sent):
    c = Client()
    assert c.get(pub('short')).status_code == 404
    assert c.get(pub('x' * 32)).status_code == 404
    assert c.post(pub('x' * 32, 'respond/'), {'action': 'accept'}, content_type='application/json').status_code == 404
    assert c.get(pub('x' * 32, 'pdf/')).status_code == 404


def test_drafts_are_not_public(db, api):
    q = api.post('/api/quotations/', {'client_name': 'A', 'items': [{'description': 'x', 'quantity': 1, 'unit_price': 5}]}, format='json').data
    obj = Quotation.objects.get(pk=q['id']); obj.ensure_public_token()
    assert Client().get(pub(obj.public_token)).status_code == 404


def test_accept_requires_name_and_tick_then_records_everything(sent, api):
    c = Client()
    url = pub(sent['token'], 'respond/')
    post = lambda body: c.post(url, body, content_type='application/json', HTTP_X_FORWARDED_FOR='203.0.113.9')
    assert post({'action': 'accept', 'name': 'J', 'agree': True}).status_code == 400
    assert post({'action': 'accept', 'name': 'Jane Buyer'}).status_code == 400
    assert post({'action': 'accept', 'name': 'Jane Buyer', 'agree': 'yes'}).status_code == 400   # must be a real true
    assert post({'action': 'maybe'}).status_code == 400
    assert Quotation.objects.get(pk=sent['id']).status == 'sent'
    ok = post({'action': 'accept', 'name': 'Jane Buyer', 'agree': True})
    assert ok.status_code == 200 and ok.json()['status'] == 'accepted'
    q = Quotation.objects.get(pk=sent['id'])
    assert q.status == 'accepted' and q.accepted_by_name == 'Jane Buyer' and q.decided_online and q.decision_ip == '203.0.113.9' and q.decided_at
    # staff notified (every admin/finance user), audit trail written, email sent to the company inbox
    assert Notification.objects.filter(title__contains='accepted online').count() == 2
    assert AuditLog.objects.filter(action='quotation_accepted_online', object_id=str(q.id)).exists()
    assert any('accepted' in m.subject for m in mail.outbox)
    # cannot be answered twice
    again = post({'action': 'decline', 'name': 'Jane Buyer'})
    assert again.status_code == 409 and Quotation.objects.get(pk=sent['id']).status == 'accepted'
    # staff see who accepted, and can convert it to an invoice
    d = api.get(f"/api/quotations/{sent['id']}/").data
    assert d['decided_online'] and d['accepted_by_name'] == 'Jane Buyer' and d['view_count'] == 0
    c2 = api.post(f"/api/quotations/{sent['id']}/action/", {'action': 'convert'}, format='json')
    assert c2.status_code == 200 and Invoice.objects.filter(invoice_number=c2.data['invoice_number']).exists()
    # the page now shows the accepted state
    assert c.get(pub(sent['token'])).json()['status'] == 'invoiced' and c.get(pub(sent['token'])).json()['can_respond'] is False


def test_decline_with_reason(sent):
    r = Client().post(pub(sent['token'], 'respond/'), {'action': 'decline', 'name': 'Bob', 'note': 'Too expensive'}, content_type='application/json')
    assert r.status_code == 200
    q = Quotation.objects.get(pk=sent['id'])
    assert q.status == 'declined' and q.decision_note == 'Too expensive' and q.decided_online
    assert Notification.objects.filter(title__contains='declined online').exists()


def test_expired_quote_cannot_be_accepted(sent):
    Quotation.objects.filter(pk=sent['id']).update(valid_until=date.today() - timedelta(days=1))
    c = Client()
    d = c.get(pub(sent['token'])).json()
    assert d['status'] == 'expired' and d['can_respond'] is False
    r = c.post(pub(sent['token'], 'respond/'), {'action': 'accept', 'name': 'Jane Buyer', 'agree': True}, content_type='application/json')
    assert r.status_code == 409 and Quotation.objects.get(pk=sent['id']).status == 'sent'


def test_resending_expired_quote_reopens_it_and_replacing_link_kills_old(sent, api):
    Quotation.objects.filter(pk=sent['id']).update(valid_until=date.today() - timedelta(days=3))
    r = api.post(f"/api/quotations/{sent['id']}/action/", {'action': 'send'}, format='json').data
    assert r['valid_until'] >= (date.today() + timedelta(days=29)).isoformat()
    assert Client().get(pub(sent['token'])).json()['can_respond'] is True
    new = api.post(f"/api/quotations/{sent['id']}/action/", {'action': 'regenerate_link'}, format='json').data['public_url']
    assert new != sent['url']
    assert Client().get(pub(sent['token'])).status_code == 404
    assert Client().get(pub(new.rstrip('/').rsplit('/', 1)[1])).status_code == 200


def test_public_pdf_and_page_and_bogus_auth_header(sent):
    c = Client()
    r = c.get(pub(sent['token'], 'pdf/'), HTTP_AUTHORIZATION='Bearer not-a-real-token')
    assert r.status_code == 200 and r.content.startswith(b'%PDF')
    page = c.get(f"/quote/{sent['token']}/")
    assert page.status_code == 200 and b'Your decision' in page.content
    assert c.get(pub(sent['token']), HTTP_AUTHORIZATION='Bearer garbage').status_code == 200


def test_respond_is_rate_limited(sent):
    c = Client()
    codes = [c.post(pub(sent['token'], 'respond/'), {'action': 'accept'}, content_type='application/json').status_code for _ in range(12)]
    assert codes[:10] == [400] * 10 and 429 in codes[10:]


def test_email_contains_link_and_pdf(sent, api):
    api.post(f"/api/quotations/{sent['id']}/action/", {'action': 'send', 'email': True}, format='json')
    msg = mail.outbox[-1]
    assert sent['url'] in msg.body and msg.attachments[0][0].endswith('.pdf')


def test_staff_can_still_record_acceptance_manually(db, api):
    q = api.post('/api/quotations/', {'client_name': 'A', 'items': [{'description': 'x', 'quantity': 1, 'unit_price': 5}]}, format='json').data
    r = api.post(f"/api/quotations/{q['id']}/action/", {'action': 'accept'}, format='json').data
    assert r['status'] == 'accepted' and 'recorded by staff' in r['accepted_by_name'] and r['decided_online'] is False

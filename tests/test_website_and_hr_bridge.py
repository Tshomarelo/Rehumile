import pytest
from django.test import Client

from HR.services.access import roles_for
from ims.models import ServicePrice, WebsiteContent
from tests.conftest import client_for, make_user


def test_website_reads_public_writes_staff_only(db, api):
    from ims.website_defaults import CONTENT_DEFAULTS
    assert api.post('/api/website/seed/').status_code == 200
    anon = Client()
    assert anon.get('/api/website/prices/').status_code == 200
    assert anon.get('/api/website/content/').status_code == 200
    client_user = client_for(make_user('client'))
    sp = ServicePrice.objects.filter(group='hardware').first()
    assert client_user.patch(f'/api/website/prices/{sp.id}/', {'price': 1}, format='json').status_code == 403
    assert client_user.post('/api/website/content/', {'key': 'x', 'value': 'y'}, format='json').status_code == 403
    assert api.patch(f'/api/website/prices/{sp.id}/', {'price': '312.5'}, format='json').status_code == 200
    sp.refresh_from_db()
    assert float(sp.price) == 312.5
    assert api.patch(f'/api/website/prices/{sp.id}/', {'price': '-3'}, format='json').status_code == 400
    # seeding never overwrites an edited value
    c = WebsiteContent.objects.get(key='hero_stat_devices'); c.value = '900+'; c.save()
    api.post('/api/website/seed/')
    assert WebsiteContent.objects.get(key='hero_stat_devices').value == '900+'
    rows = anon.get('/api/website/content/').json()
    assert next(r for r in rows if r['key'] == 'hero_stat_devices')['is_live'] is True


def test_hr_roles_map_from_portal_roles(db):
    assert 'SUPER_ADMIN' in roles_for(make_user('admin'))
    assert 'PAYROLL_ADMIN' in roles_for(make_user('finance'))
    assert not ({'SUPER_ADMIN', 'PAYROLL_ADMIN', 'HR_ADMIN'} & roles_for(make_user('cashier')))


def test_login_opens_session_for_hr_pages(db):
    u = make_user('admin')
    c = Client()
    r = c.post('/api/auth/login/', {'email': u.email, 'password': 'Pw12345!x'}, content_type='application/json')
    assert r.status_code == 200
    assert c.get('/hr/manage/').status_code == 200          # session cookie works for the HR admin site
    assert Client().get('/hr/manage/').status_code == 302    # anonymous is sent to sign in


def test_session_from_token_and_non_staff_blocked(db):
    admin_c = client_for(make_user('admin'))
    assert admin_c.post('/api/auth/session/').status_code == 200
    plain = Client(); plain.force_login(make_user('client'))
    assert plain.get('/hr/manage/').status_code == 403

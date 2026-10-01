import pytest
from rest_framework.test import APIClient

from ims.models import User


def make_user(role, n=[0]):
    n[0] += 1
    return User.objects.create_user(
        username=f"{role}{n[0]}", email=f"{role}{n[0]}@example.com", password="Pw12345!x",
        first_name=role.title(), last_name="Tester", role=role,
    )


@pytest.fixture
def admin(db):
    return make_user('admin')


@pytest.fixture
def finance_user(db):
    return make_user('finance')


@pytest.fixture
def cashier(db):
    return make_user('cashier')


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def api(admin):
    return client_for(admin)


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    """Tests are written around mid-September 2026; pin 'now' so they do not depend on the real date."""
    from datetime import datetime, timezone as dt_tz
    from django.utils import timezone
    fixed = datetime(2026, 9, 15, 10, 0, tzinfo=dt_tz.utc)
    monkeypatch.setattr(timezone, 'now', lambda: fixed)

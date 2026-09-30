import pathlib
import re
from datetime import date, datetime

import pytest
from django.utils import timezone

from ims import finance
from ims.models import Invoice
from ims.timeutils import day_bounds, parse_day, since, until

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_parse_day_never_raises():
    assert parse_day('') is None and parse_day('garbage') is None and parse_day(None) is None
    assert parse_day('2026-09-30') == date(2026, 9, 30)
    assert since('created_at', 'nope') == {} and until('created_at', '') == {}


def test_bad_date_param_is_ignored(api, db):
    r = api.get('/api/invoices/?date_from=not-a-date&date_to=xx')
    assert r.status_code == 200


def test_midnight_boundary_lands_in_johannesburg_day(db):
    start, end = day_bounds(date(2026, 9, 1))
    assert timezone.localtime(start).hour == 0 and timezone.localtime(start).day == 1
    # 00:30 SAST on 1 Sep is 22:30 UTC on 31 Aug: must count as September, not August
    inv = Invoice.objects.create(invoice_number='INV-MID-1', subtotal=100, tax_amount=0, total_amount=100, status='sent', ticket_count=0, hours_worked=0, wholesale_cost=0,
                                 due_date=date(2026, 9, 30),
                                 billing_period_start=date(2026, 9, 1), billing_period_end=date(2026, 9, 30))
    Invoice.objects.filter(pk=inv.pk).update(sent_at=start + timezone.timedelta(minutes=30))
    sept = Invoice.objects.filter(**since('sent_at', '2026-09-01'), **until('sent_at', '2026-09-30'))
    aug = Invoice.objects.filter(**since('sent_at', '2026-08-01'), **until('sent_at', '2026-08-31'))
    assert sept.count() == 1 and aug.count() == 0


def test_no_date_transform_lookups_on_datetimes():
    pat = re.compile(r"__date(__\w+)?\s*=|__date['\"]")
    bad = []
    for base in ('ims', 'HR'):
        for p in (ROOT / base).rglob('*.py'):
            s = str(p)
            if 'migrations' in s or 'tests' in s or p.name == 'timeutils.py':
                continue
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if '__date' in line and 'shift__date' not in line and pat.search(line):
                    bad.append(f'{p.relative_to(ROOT)}:{i}')
    assert not bad, bad

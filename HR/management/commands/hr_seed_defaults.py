from datetime import date
from decimal import Decimal as D

from django.core.management.base import BaseCommand

from HR.models import Company, LeavePolicy, LeaveType, PublicHoliday


class Command(BaseCommand):
    help = ("Create a starting company, leave types, a default leave policy and the 2026 South African public "
            "holidays. Safe to run again (nothing is duplicated). These are STARTING POINTS - confirm them "
            "against the Basic Conditions of Employment Act and your own policies before go-live.")

    def add_arguments(self, parser):
        parser.add_argument('--company', default='Rehumile TMW')

    def handle(self, *args, **options):
        company, _ = Company.objects.get_or_create(name=options['company'])

        types = [
            dict(code='ANNUAL', name='Annual leave', annual_days=D('15'), accrual_method='MONTHLY', is_paid=True,
                 min_notice_days=7, colour='#1a3a5c'),
            dict(code='SICK', name='Sick leave', annual_days=D('10'), accrual_method='ANNUAL', is_paid=True,
                 attachment_required_over_days=D('2'), colour='#c0392b'),
            dict(code='FAMILY', name='Family responsibility leave', annual_days=D('3'), accrual_method='ANNUAL', is_paid=True,
                 colour='#8e44ad'),
            dict(code='UNPAID', name='Unpaid leave', annual_days=D('0'), accrual_method='NONE', is_paid=False,
                 min_notice_days=7, colour='#7f8c8d'),
        ]
        made = []
        for t in types:
            lt, created = LeaveType.objects.get_or_create(company=company, code=t['code'], defaults=t)
            made.append(lt)
            if created:
                self.stdout.write(f"  leave type: {lt.name}")

        policy, _ = LeavePolicy.objects.get_or_create(company=company, name='Standard', defaults={'is_default': True})
        policy.leave_types.add(*made)

        holidays = [
            (date(2026, 1, 1), "New Year's Day"), (date(2026, 3, 21), 'Human Rights Day'),
            (date(2026, 4, 3), 'Good Friday'), (date(2026, 4, 6), 'Family Day'), (date(2026, 4, 27), 'Freedom Day'),
            (date(2026, 5, 1), "Workers' Day"), (date(2026, 6, 16), 'Youth Day'),
            (date(2026, 8, 10), "National Women's Day (observed)"), (date(2026, 9, 24), 'Heritage Day'),
            (date(2026, 12, 16), 'Day of Reconciliation'), (date(2026, 12, 25), 'Christmas Day'), (date(2026, 12, 26), 'Day of Goodwill'),
        ]
        n = 0
        for d, name in holidays:
            _, created = PublicHoliday.objects.get_or_create(company=company, date=d, site=None, defaults={'name': name})
            n += created
        self.stdout.write(self.style.SUCCESS(
            f"{company}: {len(made)} leave types, policy '{policy.name}', {n} new public holidays. Review them before go-live."))

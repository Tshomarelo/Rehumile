from django.core.management.base import BaseCommand

from HR.models import Company
from HR.services import leave as leave_service


class Command(BaseCommand):
    help = "Credit this month's leave accruals for every company. Safe to run daily: each month is credited once."

    def add_arguments(self, parser):
        parser.add_argument('--year-end', type=int, help="Also run carry-over/expiry for this year, e.g. 2025.")

    def handle(self, *args, **options):
        for company in Company.objects.filter(is_active=True):
            n = leave_service.run_accruals(company)
            self.stdout.write(f"{company}: {n} accruals credited.")
            if options.get('year_end'):
                e = leave_service.run_year_end(company, options['year_end'])
                self.stdout.write(f"{company}: {e} balances expired for {options['year_end']}.")

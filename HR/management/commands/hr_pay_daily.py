from django.core.management.base import BaseCommand

from HR.models import Company
from HR.services import advances, sync
from HR.services.notify import notify
from HR.services.roster_db import _manager_users


class Command(BaseCommand):
    help = "Daily pay housekeeping: salary changes that reach their effective date, failed sync retries, approved advances not yet paid."

    def handle(self, *a, **kw):
        due = sync.sync_due_salaries()
        retried = sync.retry_failed()
        self.stdout.write(f"Salary changes synced: {due}; failed payruns retried: {retried}.")
        for company in Company.objects.filter(is_active=True):
            flags = advances.unpaid_flags(company)
            if flags:
                notify(_manager_users(), 'advance', "Approved advances not yet paid",
                       ", ".join(f"{a.number} ({a.employee})" for a in flags[:10]))
                self.stdout.write(f"{company}: {len(flags)} approved advance(s) unpaid.")

from django.core.management.base import BaseCommand

from HR.services import payroll


class Command(BaseCommand):
    help = "Publish payslip / tax certificate batches whose scheduled time has arrived."

    def handle(self, *a, **kw):
        self.stdout.write(f"Published {payroll.publish_due()} batch(es).")

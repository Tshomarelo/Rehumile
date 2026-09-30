from django.core.management.base import BaseCommand

from ims import collections, recurring


class Command(BaseCommand):
    help = ("Daily housekeeping: post recurring expenses that are due, mark unpaid invoices overdue, and send payment reminders. "
            "Schedule it once a day (PythonAnywhere: Tasks tab -> 'python manage.py daily_jobs'). Safe to run more than once.")

    def add_arguments(self, parser):
        parser.add_argument('--no-email', action='store_true', help='Do everything except send reminder emails.')
        parser.add_argument('--base-url', default='https://www.rehumile.co.za', help='Site address used in emailed links.')

    def handle(self, *args, **opts):
        posted = recurring.post_due()
        self.stdout.write(f"Recurring expenses posted: {len(posted)}")
        for e in posted:
            self.stdout.write(f"  {e.expense_date} {e.vendor} R{e.amount}")
        self.stdout.write(f"Invoices marked overdue: {collections.mark_overdue()}")
        self.stdout.write(f"Reminders sent: {collections.send_due_reminders(opts['base_url'], send=not opts['no_email'])}")

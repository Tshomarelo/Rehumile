from django.core.management.base import BaseCommand

from HR.services import workflow


class Command(BaseCommand):
    help = "Remind approvers of overdue requests, then escalate unanswered ones to HR. Run daily."

    def handle(self, *args, **options):
        reminded, escalated = workflow.escalate_overdue()
        self.stdout.write(f"Reminded {reminded} approver(s), escalated {escalated} request(s) to HR.")

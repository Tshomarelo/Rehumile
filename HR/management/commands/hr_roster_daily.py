from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from HR.models import Company, Roster
from HR.services import roster_db
from HR.services.notify import notify


class Command(BaseCommand):
    help = ("Daily roster housekeeping: expire unanswered swap requests and offers, warn about flags about to expire, "
            "and optionally generate the next four weeks as a draft (--generate).")

    def add_arguments(self, parser):
        parser.add_argument('--generate', action='store_true', help="Create a draft roster for the four weeks starting --weeks-ahead weeks from now.")
        parser.add_argument('--weeks-ahead', type=int, default=2)

    def handle(self, *a, generate=False, weeks_ahead=2, **kw):
        n = roster_db.expire_requests_and_offers()
        self.stdout.write(f"Expired {n} request(s)/offer(s).")
        for company in Company.objects.filter(is_active=True):
            soon = roster_db.flags_expiring(company, 30)
            if soon:
                lines = "; ".join(f"{f.employee} {f.flag} {f.expires_on:%d %b}" for f in soon[:15])
                notify(roster_db._manager_users(), 'roster', "Flags expiring within 30 days", lines)
                self.stdout.write(f"{company}: {len(soon)} flag(s) expiring.")
            if generate:
                today = timezone.localdate()
                start = today + timedelta(days=(7 - today.weekday()) + 7 * (weeks_ahead - 1))
                end = start + timedelta(days=27)
                if Roster.objects.filter(company=company, start_date=start, end_date=end).exists():
                    self.stdout.write(f"{company}: a roster for {start} to {end} already exists.")
                    continue
                r = roster_db.generate_roster(company, start, end)
                self.stdout.write(f"{company}: draft roster generated ({start} to {end}), score {r.quality_score}.")

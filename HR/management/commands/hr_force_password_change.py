from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from HR.models import SecurityProfile


class Command(BaseCommand):
    help = "Make people choose a new password at their next sign-in to the HR site."

    def add_arguments(self, parser):
        parser.add_argument('usernames', nargs='*')
        parser.add_argument('--all', action='store_true', help="Everyone except superusers.")

    def handle(self, *a, usernames=(), all=False, **kw):
        users = get_user_model().objects.all()
        users = users.filter(is_superuser=False) if all else users.filter(**{f"{get_user_model().USERNAME_FIELD}__in": usernames})
        n = 0
        for u in users:
            SecurityProfile.objects.update_or_create(user=u, defaults={'must_change_password': True})
            n += 1
        self.stdout.write(f"{n} user(s) must change their password at next sign-in.")

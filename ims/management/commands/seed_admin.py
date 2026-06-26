from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from decouple import config

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed an initial admin superuser for the IMS portal'

    def handle(self, *args, **options):
        email = 'admin@rehumile.co.za'
        password = config('IMS_ADMIN_PASSWORD')  # mandatory — no insecure fallback

        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING(f'Admin user {email} already exists. Skipping.'))
            return

        user = User.objects.create_superuser(
            username=email,
            email=email,
            password=password,
            first_name='Admin',
            last_name='Rehumile',
            role='admin',
        )
        self.stdout.write(self.style.SUCCESS(f'Admin user created: {email}'))

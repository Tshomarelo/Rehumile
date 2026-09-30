"""In-app notifications plus email. Approvals and publications are always
emailed; other categories follow the same rule until per-user channel
preferences are added."""
from django.conf import settings
from django.core.mail import send_mail

from ..models import Notification


def notify(users, category, title, message='', url='', email=True):
    seen = set()
    created = []
    for user in users:
        if user is None or user.pk in seen or not user.is_active:
            continue
        seen.add(user.pk)
        note = Notification.objects.create(user=user, category=category, title=title, message=message, url=url)
        created.append(note)
        if email and user.email:
            base = getattr(settings, 'HR_SITE_URL', 'http://127.0.0.1:8000').rstrip('/')
            body = message + (f"\n\nOpen: {base}{url}" if url else '')
            try:
                send_mail(title, body, getattr(settings, 'HR_EMAIL_FROM', None), [user.email], fail_silently=True)
                note.emailed = True
                note.save(update_fields=['emailed'])
            except Exception:
                pass
    return created

"""Private file storage for HR documents (payslips, tax certificates, proofs,
leave attachments). Files live outside MEDIA_ROOT and have no public URL: the
only way to open one is a signed, time-limited link issued to a signed-in
person who is allowed to see it (see HR.services.files)."""
from django.conf import settings
from django.core.files.storage import FileSystemStorage


def private_storage():
    # A callable, so migrations do not bake this machine's absolute path in.
    return FileSystemStorage(location=str(settings.BASE_DIR / 'private_media'), base_url=None)

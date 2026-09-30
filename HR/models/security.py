from django.conf import settings
from django.db import models

from ..fields import EncryptedTextField


class SecurityProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hr_security')
    must_change_password = models.BooleanField(default=False)
    totp_secret = EncryptedTextField(blank=True, null=True)
    totp_enabled = models.BooleanField(default=False)

    def __str__(self):
        return f"Security for {self.user}"

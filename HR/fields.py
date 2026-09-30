"""Encrypted-at-rest model fields for the HR system (ID numbers, bank accounts,
salary). Values are encrypted with Fernet before they reach the database and
decrypted when read, so a database dump alone does not expose them.

The key comes from settings.HR_FIELD_ENCRYPTION_KEY; when that is empty (local
development) one is derived from SECRET_KEY. Changing the key makes existing
values unreadable, so set it once in production and keep it out of the code.
"""
import base64
import hashlib
import logging
from decimal import Decimal, InvalidOperation

from cryptography.fernet import Fernet, InvalidToken
from django import forms
from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)
_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        key = (getattr(settings, 'HR_FIELD_ENCRYPTION_KEY', '') or '').encode()
        if not key:
            key = base64.urlsafe_b64encode(hashlib.sha256(('hr-fields:' + settings.SECRET_KEY).encode()).digest())
        _fernet = Fernet(key)
    return _fernet


def mask(value, show=4):
    """'8001015009087' -> '*********9087'. Used wherever a sensitive value is
    shown before the user re-enters their password."""
    if not value:
        return ''
    value = str(value)
    if len(value) <= show:
        return '*' * len(value)
    return '*' * (len(value) - show) + value[-show:]


class EncryptedTextField(models.TextField):
    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ''):
            return value
        return _get_fernet().encrypt(str(value).encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value in (None, ''):
            return value
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            logger.error("HR encrypted field could not be decrypted - wrong or changed HR_FIELD_ENCRYPTION_KEY?")
            return None


class EncryptedDecimalField(EncryptedTextField):
    """A decimal (for example salary) stored encrypted as text."""

    def to_python(self, value):
        if value in (None, ''):
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    def from_db_value(self, value, expression, connection):
        return self.to_python(super().from_db_value(value, expression, connection))

    def get_prep_value(self, value):
        if value in (None, ''):
            return None
        return super().get_prep_value(str(Decimal(str(value))))

    def formfield(self, **kwargs):
        defaults = {'form_class': forms.DecimalField, 'max_digits': 14, 'decimal_places': 2}
        defaults.update(kwargs)
        defaults.pop('widget', None)
        return super(models.TextField, self).formfield(**defaults)

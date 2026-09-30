"""Local/test settings — SQLite, no external services. Used by pytest (see pytest.ini)."""
import os

os.environ.setdefault('IMS_SECRET_KEY', 'test-secret-key')
os.environ.setdefault('MYSQL_PASSWORD', 'unused')

from .settings import *  # noqa: E402,F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.environ.get('TEST_DB', ':memory:'),
    }
}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

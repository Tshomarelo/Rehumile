from django.apps import AppConfig


class HRConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'HR'
    label = 'hr'
    verbose_name = 'HR System'

    def ready(self):
        from . import signals
        signals.connect()

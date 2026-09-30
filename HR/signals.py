"""Read-only guard (SM-9, SY-5): once the sync is switched on, salary and advance entries in the reconciliation
system can only be created or changed by the HR sync, never by hand."""
from django.core.exceptions import PermissionDenied


def _managed_names():
    from .models import HRSettings
    ps = HRSettings.objects.filter(salary_sync_enabled=True).first()
    if ps is None:
        return set()
    return {ps.salaries_category, ps.advance_category, ps.writeoff_category}


def guard_business_expense(sender, instance, **kwargs):
    if getattr(instance, '_hr_sync', False):
        return
    names = _managed_names()
    if not names:
        return
    cat = getattr(instance, 'category', None)
    if cat is not None and cat.name in names:
        raise PermissionDenied("Salary entries are managed in the HR system and cannot be created, changed or deleted here.")


def connect():
    from django.apps import apps
    from django.db.models.signals import pre_delete, pre_save
    try:
        model = apps.get_model('reconciliation', 'BusinessExpense')
    except LookupError:
        return
    pre_save.connect(guard_business_expense, sender=model, dispatch_uid='hr_guard_expense_save')
    pre_delete.connect(guard_business_expense, sender=model, dispatch_uid='hr_guard_expense_delete')

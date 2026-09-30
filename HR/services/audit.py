"""Write an entry to the append-only audit log."""
import json

from ..models import AuditLog


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    ip = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')
    return ip or None


def _plain(value):
    """JSON-safe copy (dates, decimals and model values become strings)."""
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str))


def log(action, module, *, request=None, user=None, obj=None, old=None, new=None,
        employee=None, sensitive=False, description=''):
    if user is None and request is not None and getattr(request, 'user', None) is not None and request.user.is_authenticated:
        user = request.user
    if employee is None and obj is not None:
        from ..models import Employee
        employee = obj if isinstance(obj, Employee) else getattr(obj, 'employee', None)
        if not isinstance(employee, Employee):
            employee = None
    return AuditLog.objects.create(
        user=user if user is not None and user.is_authenticated else None,
        username=(user.get_username() if user is not None and user.is_authenticated else ''),
        action=action, module=module,
        object_type=obj.__class__.__name__ if obj is not None else '',
        object_id=str(getattr(obj, 'pk', '') or ''),
        object_repr=(description or (str(obj) if obj is not None else ''))[:255],
        employee=employee, old_value=_plain(old), new_value=_plain(new),
        ip_address=client_ip(request), sensitive=sensitive,
    )

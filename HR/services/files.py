"""Signed, short-lived download links for private HR files."""
import os

from django.core import signing
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.urls import reverse
from django.utils import timezone

from . import audit
from .access import employee_for, has_role
from ..models import Warning, PayrunInput, EmployeeDocument, PolicyVersion, ChangeRequest, LeaveRequest, Payslip, TaxCertificate, PAYROLL_ADMIN, HR_ADMIN

SALT = 'hr.files'
MAX_AGE = 600  # ten minutes

KINDS = {
    'payslip': Payslip,
    'taxcert': TaxCertificate,
    'proof': ChangeRequest,
    'leave': LeaveRequest,
    'doc': EmployeeDocument,
    'warning': Warning,
    'receipt': PayrunInput,
    'policy': PolicyVersion,
}


def _field(obj):
    return obj.document if isinstance(obj, Warning) else obj.receipt if isinstance(obj, PayrunInput) else obj.proof if isinstance(obj, ChangeRequest) else obj.file if isinstance(obj, (EmployeeDocument, PolicyVersion)) else obj.attachment if isinstance(obj, LeaveRequest) else obj.file


def _owner(obj):
    return getattr(obj, 'employee', None)


def can_open(user, kind, obj):
    if user.is_superuser:
        return True
    me = employee_for(user)
    owner = _owner(obj)
    if kind == 'policy':
        return bool(me and me.company_id == obj.policy.company_id) or has_role(user, HR_ADMIN)
    if kind == 'receipt':
        return has_role(user, PAYROLL_ADMIN) or bool(me and owner and owner.pk == me.pk)
    if kind == 'doc' and obj.status != 'ACTIVE' and not has_role(user, HR_ADMIN):
        return False
    if kind in ('payslip', 'taxcert'):
        if has_role(user, PAYROLL_ADMIN):
            return True
        return bool(me and owner and owner.pk == me.pk and obj.status in ('PUBLISHED', 'CORRECTION'))
    if has_role(user, HR_ADMIN):
        return True
    return bool(me and owner and owner.pk == me.pk)


def make_url(user, kind, obj, download=False):
    token = signing.dumps({'k': kind, 'id': obj.pk, 'u': user.pk, 'd': download}, salt=SALT)
    return reverse('hr:file_open', args=[token])


def open_file(request, token):
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:
        return HttpResponseForbidden("This link has expired. Go back and open the document again.")
    if data['u'] != request.user.pk:
        return HttpResponseForbidden("This link was issued to someone else.")
    model = KINDS.get(data['k'])
    obj = model.objects.filter(pk=data['id']).first() if model else None
    if obj is None or not can_open(request.user, data['k'], obj) or not _field(obj):
        raise Http404
    f = _field(obj)
    now = timezone.now()
    if hasattr(obj, 'first_viewed_at') and getattr(obj, 'employee_id', None) and employee_for(request.user) and obj.employee_id == employee_for(request.user).pk:
        if not obj.first_viewed_at:
            obj.first_viewed_at = now
            obj.save(update_fields=['first_viewed_at'])
    if isinstance(obj, TaxCertificate):
        field = 'download_count' if data['d'] else 'view_count'
        setattr(obj, field, getattr(obj, field) + 1)
        obj.save(update_fields=[field])
    audit.log('file.download' if data['d'] else 'file.view', 'files', request=request, obj=obj,
              employee=_owner(obj), sensitive=True)
    resp = FileResponse(f.open('rb'), as_attachment=data['d'], filename=os.path.basename(f.name))
    resp['Cache-Control'] = 'private, no-store'
    return resp

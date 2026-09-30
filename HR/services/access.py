"""Who the logged-in person is in HR terms, and what they may see or do.

Every request is scoped by the reporting line: an employee sees only their own
record, a manager only their team, HR and Payroll see everyone.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from ..models import (
    ADMIN_ROLES, EMPLOYEE, HR_ADMIN, LINE_MANAGER, PAYROLL_ADMIN, SUPER_ADMIN,
    Company, Employee, RoleAssignment,
)


DEFAULT_COMPANY_NAME = 'Rehumile TMW'


def employee_for(user):
    if not user.is_authenticated:
        return None
    try:
        return user.hr_employee
    except ObjectDoesNotExist:
        return None


def roles_for(user):
    if not user.is_authenticated:
        return set()
    roles = set(RoleAssignment.objects.filter(user=user).values_list('role', flat=True))
    if user.is_superuser:
        roles.add(SUPER_ADMIN)
    # Rehumile portal roles carry over: HQ administrators run HR, finance runs payroll.
    portal_role = getattr(user, 'role', None)
    if portal_role == 'admin':
        roles.add(SUPER_ADMIN)
    elif portal_role == 'finance':
        roles.add(PAYROLL_ADMIN)
    emp = employee_for(user)
    if emp is not None:
        roles.add(EMPLOYEE)
        if emp.direct_reports.exists():
            roles.add(LINE_MANAGER)
    return roles


def has_role(user, *roles):
    return bool(roles_for(user) & set(roles))


def is_admin_user(user):
    return bool(roles_for(user) & ADMIN_ROLES)


def sees_everyone(user):
    return has_role(user, HR_ADMIN, PAYROLL_ADMIN, SUPER_ADMIN)


def team_of(user):
    """Employees this user may see: everyone for HR/Payroll/Super Admin, their
    reporting line for a manager, nobody otherwise."""
    if sees_everyone(user):
        return Employee.objects.all()
    emp = employee_for(user)
    if emp is not None and emp.direct_reports.exists():
        ids = [e.pk for e in emp.all_reports()]
        return Employee.objects.filter(pk__in=ids)
    return Employee.objects.none()


def can_view_employee(user, employee):
    emp = employee_for(user)
    if emp is not None and emp.pk == employee.pk:
        return True
    return team_of(user).filter(pk=employee.pk).exists()


def current_company(request):
    """The company the admin site is working in (session), defaulting to the
    user's own or the first company."""
    cid = request.session.get('hr_company_id')
    if cid:
        company = Company.objects.filter(pk=cid, is_active=True).first()
        if company:
            return company
    emp = employee_for(request.user)
    if emp is not None:
        return emp.company
    company = Company.objects.filter(is_active=True).first()
    if company is None and not Company.objects.exists():
        # Fresh install: start with Rehumile itself so nothing has to be set up before first use.
        company = Company.objects.create(name=DEFAULT_COMPANY_NAME)
    return company


# ------------------------------------------------------------- decorators
def portal_required(view):
    """Logged in AND linked to an employee record."""
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if employee_for(request.user) is None:
            return render(request, 'hr/no_employee.html', status=403)
        return view(request, *args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not has_role(request.user, *roles):
                return HttpResponseForbidden("You do not have access to this page.")
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def manager_or_admin_required(view):
    return role_required(LINE_MANAGER, 'SENIOR_MANAGER', HR_ADMIN, PAYROLL_ADMIN, SUPER_ADMIN)(view)

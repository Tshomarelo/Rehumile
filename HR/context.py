"""Template context for the HR pages only (kept cheap: nothing runs elsewhere)."""
from .models import ADMIN_ROLES, LINE_MANAGER, Company, Notification
from .services.access import current_company, employee_for, roles_for
from .services.workflow import pending_steps_for


def hr(request):
    if not request.path.startswith('/hr/') or not request.user.is_authenticated:
        return {}
    roles = roles_for(request.user)
    can_approve = bool(roles & (ADMIN_ROLES | {LINE_MANAGER}))
    companies = Company.objects.filter(is_active=True)
    return {
        'hr_roles': roles,
        'hr_is_admin': bool(roles & ADMIN_ROLES),
        'hr_is_payroll': bool(roles & {'PAYROLL_ADMIN', 'SUPER_ADMIN'}),
        'hr_is_manager': LINE_MANAGER in roles,
        'hr_can_manage': can_approve,
        'hr_employee': employee_for(request.user),
        'hr_unread': Notification.objects.filter(user=request.user, read_at__isnull=True).count(),
        'hr_pending_count': len(pending_steps_for(request.user)) if can_approve else 0,
        'hr_company': current_company(request),
        # the company selector only appears when there is more than one to pick
        'hr_companies': companies if companies.count() > 1 and (roles & ADMIN_ROLES) else [],
    }

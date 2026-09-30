from django.utils.http import url_has_allowed_host_and_scheme
"""The admin site: dashboard and approval queue for managers, and maintenance
of employees, organisation, leave and settings for HR, payroll and super admin."""
import csv
from datetime import date, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, ProtectedError
from django.forms import modelform_factory, model_to_dict
from django import forms as dj_forms
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import (
    DATE, EmployeeForm, EmploymentRecordForm, LeaveAdjustForm, LeaveCaptureForm, RoleAssignmentForm,
    StyledModelForm, WorkflowDefinitionForm,
)
from ..models import (
    ADMIN_ROLES, HR_ADMIN, LINE_MANAGER, PAYROLL_ADMIN, SUPER_ADMIN,
    ApprovalStep, AuditLog, BlackoutPeriod, Company, CostCentre, Department, Employee, EmploymentRecord,
    LeavePolicy, LeaveRequest, LeaveType, Position, PublicHoliday, RoleAssignment, Site, WorkflowDefinition,
    POS, StaffGroup, Flag, Post, ShiftTemplate, OpenPOS, DemandRule, DemandOverride, RequiredHours, RosterSettings,
    RosterProfile, EmployeeFlag, SiteApproval, AdvancePolicy,
)
from ..timeutils import since, until
from ..services import audit, workflow
from ..services import leave as L
from ..services.access import (
    current_company, employee_for, has_role, manager_or_admin_required, role_required, roles_for, team_of,
)
from ..services.workflow import WorkflowError

HR_STAFF = (HR_ADMIN, PAYROLL_ADMIN, SUPER_ADMIN)


# ----------------------------------------------------------------- dashboard
@manager_or_admin_required
def dashboard(request):
    company = current_company(request)
    today = timezone.localdate()
    scope = team_of(request.user)
    if company is not None:
        scope = scope.filter(company=company)
    pending = workflow.pending_steps_for(request.user)
    on_leave_today = LeaveRequest.objects.filter(
        employee__in=scope, status__in=['APPROVED', 'CANCEL_REQUESTED'], start_date__lte=today, end_date__gte=today
    ).select_related('employee', 'leave_type')
    next_week = LeaveRequest.objects.filter(
        employee__in=scope, status='APPROVED', start_date__gt=today, start_date__lte=today + timedelta(days=7)
    ).count()
    active = scope.exclude(status='TERMINATED')
    setup = None
    if has_role(request.user, *HR_STAFF) and company is not None:
        setup = [
            ('Employees', Employee.objects.filter(company=company).count(), 'hr:manage_employees'),
            ('Leave types', LeaveType.objects.filter(company=company).count(), None),
            ('Leave policies', LeavePolicy.objects.filter(company=company).count(), None),
            ('Public holidays', PublicHoliday.objects.filter(company=company).count(), None),
        ]
    return render(request, 'hr/manage/dashboard.html', {
        'pending': pending[:8], 'pending_total': len(pending), 'on_leave_today': on_leave_today,
        'next_week': next_week, 'headcount': active.count(),
        'new_starters': active.filter(start_date__gte=today - timedelta(days=30)).count(),
        'setup': setup, 'company': company, 'active': 'dashboard',
    })


# ---------------------------------------------------------------- approvals
@manager_or_admin_required
def approvals(request):
    mine = workflow.pending_steps_for(request.user)
    decided = ApprovalStep.objects.filter(acted_by=request.user).select_related('instance').order_by('-acted_at')[:15]
    from ..models import ChangeRequest
    from ..services import biographical as B, files
    mine = list(mine)
    for s_ in mine:
        subj = s_.instance.subject
        if isinstance(subj, ChangeRequest):
            s_.diff = B.diff_rows(subj)
            s_.proof_url = files.make_url(request.user, 'proof', subj) if subj.proof else ''
    return render(request, 'hr/manage/approvals.html', {'steps': mine, 'decided': decided, 'active': 'approvals'})


@manager_or_admin_required
@require_POST
def approval_decide(request, step_id):
    step = get_object_or_404(ApprovalStep.objects.select_related('instance'), pk=step_id)
    comment = request.POST.get('comment', '').strip()
    try:
        if request.POST.get('action') == 'approve':
            workflow.approve(step, request.user, comment)
            messages.success(request, "Approved.")
        else:
            workflow.reject(step, request.user, comment)
            messages.success(request, "Declined. The requester has been told why.")
    except WorkflowError as e:
        messages.error(request, str(e))
    return redirect('hr:manage_approvals')


@manager_or_admin_required
def team(request):
    """A manager's team with the details they are allowed to see."""
    people = team_of(request.user)
    emp = employee_for(request.user)
    today = timezone.localdate()
    off = set(LeaveRequest.objects.filter(status='APPROVED', start_date__lte=today, end_date__gte=today).values_list('employee_id', flat=True))
    people = people.exclude(status='TERMINATED').select_related('position', 'department', 'manager')
    return render(request, 'hr/manage/team.html', {'people': people, 'off': off, 'emp': emp, 'active': 'team'})


@role_required(*HR_STAFF)
def switch_company(request, pk):
    company = get_object_or_404(Company, pk=pk, is_active=True)
    request.session['hr_company_id'] = company.pk
    return redirect(request.META.get('HTTP_REFERER') or 'hr:manage_home')


# ---------------------------------------------------------------- employees
@role_required(*HR_STAFF)
def employees(request):
    company = current_company(request)
    qs = Employee.objects.filter(company=company).select_related('position', 'department', 'manager')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(known_as__icontains=q) | Q(surname__icontains=q) | Q(first_names__icontains=q) | Q(employee_number__icontains=q))
    status = request.GET.get('status', 'ACTIVE')
    if status == 'ACTIVE':
        qs = qs.exclude(status='TERMINATED')
    elif status:
        qs = qs.filter(status=status)
    dept = request.GET.get('department')
    if dept:
        qs = qs.filter(department_id=dept)
    page = Paginator(qs, 50).get_page(request.GET.get('page'))
    return render(request, 'hr/manage/employees.html', {
        'page': page, 'q': q, 'status': status, 'dept': dept,
        'departments': Department.objects.filter(company=company), 'company': company, 'active': 'employees',
    })


@role_required(*HR_STAFF)
def employee_detail(request, pk):
    emp = get_object_or_404(Employee.objects.select_related('company', 'position', 'department', 'site', 'manager', 'user'), pk=pk)
    reveal = request.GET.get('reveal') == '1'
    if reveal:
        audit.log('employee.reveal', 'employee', request=request, obj=emp, sensitive=True,
                  description=f"Viewed ID number and salary of {emp.display_name}")
    return render(request, 'hr/manage/employee_detail.html', {
        'e': emp, 'reveal': reveal, 'records': emp.records.select_related('position', 'department', 'manager'),
        'balances': L.balances_for(emp), 'requests': emp.leave_requests.select_related('leave_type')[:10],
        'roles': RoleAssignment.objects.filter(user=emp.user) if emp.user_id else [], 'active': 'employees',
    })


@role_required(*HR_STAFF)
def employee_edit(request, pk=None):
    company = current_company(request)
    emp = get_object_or_404(Employee, pk=pk) if pk else None
    old = model_to_dict(emp, exclude=['id_number', 'photo']) if emp else None
    if not has_role(request.user, HR_ADMIN, SUPER_ADMIN):
        messages.error(request, "Only HR can edit the employee master record.")
        return redirect('hr:manage_employees')
    form = EmployeeForm(company, request.POST or None, instance=emp)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.company = emp.company if emp else company
        obj.save()
        audit.log('employee.update' if emp else 'employee.create', 'employee', request=request, obj=obj, sensitive=True,
                  old=old, new=model_to_dict(obj, exclude=['id_number', 'photo']))
        messages.success(request, "Employee saved." if emp else "Employee created. Now add their job and pay details.")
        if not emp:
            return redirect('hr:manage_employee_record', pk=obj.pk)
        return redirect('hr:manage_employee', pk=obj.pk)
    return render(request, 'hr/manage/employee_form.html', {'form': form, 'e': emp, 'active': 'employees'})


@role_required(*HR_STAFF)
def employee_add_record(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    show_salary = has_role(request.user, HR_ADMIN, PAYROLL_ADMIN, SUPER_ADMIN)
    initial = {'effective_from': emp.start_date or timezone.localdate()}
    cur = emp.record_on()
    if cur:
        initial.update({f: getattr(cur, f) for f in ('position', 'department', 'site', 'cost_centre', 'manager', 'contract_type', 'pay_type', 'hours_per_week')})
    form = EmploymentRecordForm(emp.company, emp, request.POST or None, initial=initial, show_salary=show_salary)
    if request.method == 'POST' and form.is_valid():
        rec = form.save(commit=False)
        rec.employee = emp
        rec.created_by = request.user
        rec.save()
        audit.log('employment.record', 'employee', request=request, obj=rec, employee=emp, sensitive=True,
                  new={'effective_from': rec.effective_from, 'reason': rec.reason, 'position': str(rec.position), 'manager': str(rec.manager), 'pay_changed': show_salary})
        messages.success(request, "Employment details saved (effective %s)." % rec.effective_from)
        return redirect('hr:manage_employee', pk=emp.pk)
    return render(request, 'hr/manage/record_form.html', {'form': form, 'e': emp, 'active': 'employees'})


# --------------------------------------------------------------- roles / audit
@role_required(SUPER_ADMIN)
def roles(request):
    form = RoleAssignmentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ra = form.save()
        audit.log('role.grant', 'security', request=request, obj=ra, sensitive=True, new={'user': ra.user.get_username(), 'role': ra.role})
        messages.success(request, "Role granted.")
        return redirect('hr:manage_roles')
    return render(request, 'hr/manage/roles.html', {
        'form': form, 'assignments': RoleAssignment.objects.select_related('user', 'company'), 'active': 'roles'})


@role_required(SUPER_ADMIN)
@require_POST
def role_delete(request, pk):
    ra = get_object_or_404(RoleAssignment, pk=pk)
    audit.log('role.revoke', 'security', request=request, obj=ra, sensitive=True, old={'user': ra.user.get_username(), 'role': ra.role})
    ra.delete()
    messages.success(request, "Role removed.")
    return redirect('hr:manage_roles')


def _audit_queryset(request):
    qs = AuditLog.objects.select_related('user', 'employee')
    g = request.GET
    if g.get('user'):
        qs = qs.filter(username__icontains=g['user'])
    if g.get('employee'):
        qs = qs.filter(Q(employee__known_as__icontains=g['employee']) | Q(employee__surname__icontains=g['employee']))
    if g.get('module'):
        qs = qs.filter(module=g['module'])
    if g.get('from'):
        qs = qs.filter(**since('timestamp', g['from']))
    if g.get('to'):
        qs = qs.filter(**until('timestamp', g['to']))
    if g.get('sensitive'):
        qs = qs.filter(sensitive=True)
    return qs


@role_required(SUPER_ADMIN)
def audit_log(request):
    page = Paginator(_audit_queryset(request), 100).get_page(request.GET.get('page'))
    modules = AuditLog.objects.order_by().values_list('module', flat=True).distinct()
    return render(request, 'hr/manage/audit.html', {'page': page, 'modules': modules, 'get': request.GET, 'active': 'audit'})


@role_required(SUPER_ADMIN)
def audit_export(request):
    audit.log('audit.export', 'security', request=request, description="Exported the audit log to CSV", sensitive=True)
    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = 'attachment; filename="hr-audit-log.csv"'
    w = csv.writer(resp)
    w.writerow(['time', 'user', 'action', 'module', 'record', 'employee', 'old', 'new', 'ip', 'sensitive'])
    for a in _audit_queryset(request)[:20000]:
        w.writerow([a.timestamp.isoformat(), a.username, a.action, a.module, a.object_repr,
                    a.employee.display_name if a.employee else '', a.old_value or '', a.new_value or '', a.ip_address or '', a.sensitive])
    return resp


# ------------------------------------------------------------ leave admin
@role_required(*HR_STAFF)
def leave_requests(request):
    company = current_company(request)
    status = request.GET.get('status', '')
    qs = LeaveRequest.objects.filter(employee__company=company).select_related('employee', 'leave_type')
    if status:
        qs = qs.filter(status=status)
    page = Paginator(qs, 50).get_page(request.GET.get('page'))
    return render(request, 'hr/manage/leave_requests.html', {'page': page, 'status': status, 'choices': LeaveRequest.STATUS_CHOICES, 'active': 'leave'})


@role_required(HR_ADMIN, SUPER_ADMIN)
def leave_capture(request):
    company = current_company(request)
    form = LeaveCaptureForm(company, request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        emp = d['employee']
        submitter = emp.user if emp.user_id else request.user
        req, errors = L.create_request(emp, d['leave_type'], d['start_date'], d['end_date'], d['half_day_start'],
                                       d['half_day_end'], d['reason'], d.get('attachment'), submitter, captured_by=request.user)
        if errors:
            for e in errors:
                form.add_error(None, e)
        else:
            if d['approve_now']:
                inst = L.latest_instance(req)
                workflow.approve(inst.current_step, request.user, "Captured and approved by HR", on_behalf=True)
            messages.success(request, "Leave captured for %s." % emp.display_name)
            return redirect('hr:leave_detail', pk=req.pk)
    return render(request, 'hr/manage/leave_capture.html', {'form': form, 'active': 'leave'})


@role_required(HR_ADMIN, SUPER_ADMIN)
def leave_adjust(request):
    company = current_company(request)
    form = LeaveAdjustForm(company, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            L.adjust_balance(d['employee'], d['leave_type'], d['days'], d['reason'], request.user)
            messages.success(request, "Balance adjusted and logged.")
            return redirect('hr:manage_leave_balances')
        except WorkflowError as e:
            form.add_error(None, str(e))
    return render(request, 'hr/manage/leave_adjust.html', {'form': form, 'active': 'leave'})


@role_required(HR_ADMIN, SUPER_ADMIN)
@require_POST
def leave_run_accruals(request):
    company = current_company(request)
    if request.POST.get('run') == 'year_end':
        year = int(request.POST.get('year') or timezone.localdate().year - 1)
        n = L.run_year_end(company, year, request.user)
        messages.success(request, f"Year-end for {year}: {n} balances had days above the carry-over limit expire.")
    else:
        n = L.run_accruals(company, timezone.localdate(), request.user)
        messages.success(request, f"Accrual run complete: {n} new accruals credited (already-credited months are skipped).")
    return redirect('hr:manage_leave_balances')


@role_required(*HR_STAFF)
def leave_balances(request):
    company = current_company(request)
    types = LeaveType.objects.filter(company=company, is_active=True)
    rows = []
    for e in Employee.objects.filter(company=company).exclude(status='TERMINATED').select_related('position'):
        by_type = {b['leave_type'].pk: b for b in L.balances_for(e)}
        rows.append({'e': e, 'cells': [by_type.get(t.pk) for t in types]})
    return render(request, 'hr/manage/leave_balances.html', {'types': types, 'rows': rows, 'year': timezone.localdate().year, 'active': 'leave'})


# ---------------------------------------------------------- generic setup CRUD
RS = (HR_ADMIN, SUPER_ADMIN)


def _registry():
    return {
        'companies': dict(model=Company, title='Companies', roles=(SUPER_ADMIN,), scoped=False,
                          cols=['name', 'legal_name', 'retirement_age', 'is_active'],
                          fields=['name', 'legal_name', 'logo', 'banner', 'primary_colour', 'retirement_age', 'work_days',
                                  'show_team_leave_names', 'information_officer', 'is_active']),
        'sites': dict(model=Site, title='Sites', roles=HR_STAFF, cols=['name', 'site_type', 'open_time', 'close_time', 'is_24h', 'is_active'],
                      fields=['name', 'address', 'site_type', 'open_time', 'close_time', 'is_24h', 'open_days', 'setup_minutes', 'cashup_minutes',
                              'auto_confirm_offers', 'managers', 'is_active']),
        'pos': dict(model=POS, title='POS terminals', roles=RS, cols=['site', 'name', 'is_active'], fields=['site', 'name', 'is_active']),
        'staff-groups': dict(model=StaffGroup, title='Staff groups', roles=RS, cols=['name', 'is_casual', 'pattern_based', 'hours_30_31', 'hours_february'],
                             fields=['name', 'is_casual', 'pattern_based', 'hours_30_31', 'hours_february', 'min_off_days_per_week', 'max_consecutive_days',
                                     'weekend_rotation_weeks', 'weekend_mode', 'weekend_days', 'min_on_duty_per_weekend', 'pattern_site', 'pattern_post',
                                     'weekday_template', 'weekend_template', 'is_active']),
        'flags': dict(model=Flag, title='Flags', roles=RS, cols=['name', 'description'], fields=['name', 'description']),
        'posts': dict(model=Post, title='Posts', roles=RS, cols=['site', 'name', 'continuous_cover', 'fair_share', 'is_active'],
                      fields=['site', 'name', 'staff_groups', 'alt_groups', 'required_flags', 'continuous_cover', 'fair_share', 'is_active']),
        'shift-templates': dict(model=ShiftTemplate, title='Shifts', roles=RS, cols=['site', 'name', 'start_time', 'end_time', 'paid_hours', 'break_type', 'is_active'],
                                fields=['site', 'name', 'day_types', 'start_time', 'paid_hours', 'break_type', 'break_minutes', 'break_window', 'paid_rest_minutes',
                                        'pay_night', 'pay_sunday', 'pay_holiday', 'pay_weekend', 'effective_from', 'effective_to', 'compliance_basis', 'is_active']),
        'open-pos': dict(model=OpenPOS, title='Open POS', roles=RS, cols=['template', 'day_type', 'count'], fields=['template', 'day_type', 'count']),
        'demand-rules': dict(model=DemandRule, title='Demand rules', roles=RS, cols=['site', 'template', 'post', 'rule_type', 'minimum', 'target', 'maximum', 'priority'],
                             fields=['site', 'template', 'post', 'day_types', 'rule_type', 'minimum', 'target', 'maximum', 'per_unit', 'priority', 'effective_from', 'effective_to']),
        'demand-overrides': dict(model=DemandOverride, title='Demand overrides', roles=RS, cols=['site', 'start_date', 'end_date', 'minimum', 'reason'],
                                 fields=['site', 'start_date', 'end_date', 'template', 'post', 'minimum', 'target', 'maximum', 'reason']),
        'required-hours': dict(model=RequiredHours, title='Required hours', roles=RS, cols=['staff_group', 'employee', 'effective_from', 'hours_30_31', 'hours_february'],
                               fields=['staff_group', 'employee', 'effective_from', 'hours_30_31', 'hours_february', 'note']),
        'roster-settings': dict(model=RosterSettings, title='Roster rules', roles=RS, cols=['company', 'max_consecutive_days', 'min_rest_hours', 'max_week_hours', 'tolerance_hours'],
                                fields=['max_consecutive_days', 'min_rest_hours', 'weekly_rest_hours', 'max_week_hours', 'max_overtime_hours', 'max_night_run',
                                        'min_off_days_per_week', 'tolerance_hours', 'leave_counts_toward_hours', 'leave_counts_as_off_day', 'min_notice_hours',
                                        'swap_auto_approve', 'request_expiry_hours', 'month_basis', 'pay_period_start_day']),
        'roster-profiles': dict(model=RosterProfile, title='Staff roster profiles', roles=RS, cols=['employee', 'staff_group', 'weekend_team', 'casual_rate'],
                                fields=['employee', 'staff_group', 'weekend_team', 'casual_pay_basis', 'casual_rate', 'weekly_hours_cap', 'casual_priority', 'sms_number']),
        'employee-flags': dict(model=EmployeeFlag, title='Staff flags', roles=RS, cols=['employee', 'flag', 'effective_from', 'expires_on'],
                               fields=['employee', 'flag', 'effective_from', 'expires_on']),
        'advance-policies': dict(model=AdvancePolicy, title='Advance policies', roles=RS, cols=['staff_group', 'allowed', 'max_amount', 'max_percent_of_earned', 'open_advances', 'recovery_max_payruns', 'tier1_limit'],
                                 fields=['staff_group', 'allowed', 'casual_only_against_shifts_worked', 'max_amount', 'max_percent_of_earned', 'open_advances', 'min_days_between',
                                         'min_months_service', 'max_unpaid_balance', 'block_on_final_warning', 'recovery_max_payruns', 'max_recovery_percent_of_pay',
                                         'tier1_limit', 'fee_percent']),
        'site-approvals': dict(model=SiteApproval, title='Site approvals', roles=RS, cols=['employee', 'site', 'post'], fields=['employee', 'site', 'post']),
        'departments': dict(model=Department, title='Departments', roles=HR_STAFF, cols=['name', 'parent', 'is_active'], fields=['name', 'parent', 'is_active']),
        'positions': dict(model=Position, title='Positions', roles=HR_STAFF, cols=['title', 'department', 'is_active'], fields=['title', 'department', 'is_active']),
        'cost-centres': dict(model=CostCentre, title='Cost centres', roles=HR_STAFF, cols=['code', 'name', 'is_active'], fields=['code', 'name', 'is_active']),
        'leave-types': dict(model=LeaveType, title='Leave types', roles=(HR_ADMIN, SUPER_ADMIN),
                            cols=['name', 'code', 'annual_days', 'accrual_method', 'is_paid', 'is_active'],
                            fields=['name', 'code', 'is_paid', 'annual_days', 'accrual_method', 'carry_over_max', 'allow_negative',
                                    'max_negative_days', 'half_days_allowed', 'min_notice_days', 'attachment_required_over_days', 'colour', 'is_active']),
        'leave-policies': dict(model=LeavePolicy, title='Leave policies', roles=(HR_ADMIN, SUPER_ADMIN), cols=['name', 'is_default'], fields=['name', 'leave_types', 'is_default']),
        'holidays': dict(model=PublicHoliday, title='Public holidays', roles=(HR_ADMIN, SUPER_ADMIN), cols=['date', 'name', 'site'], fields=['date', 'name', 'site']),
        'blackouts': dict(model=BlackoutPeriod, title='Blackout periods', roles=(HR_ADMIN, SUPER_ADMIN),
                          cols=['start_date', 'end_date', 'reason', 'department', 'leave_type'],
                          fields=['start_date', 'end_date', 'reason', 'department', 'leave_type']),
        'workflows': dict(model=WorkflowDefinition, title='Approval workflows', roles=(SUPER_ADMIN,), form_class=WorkflowDefinitionForm,
                          cols=['key', 'steps', 'escalation_days', 'is_active'], fields=None),
    }


def _entry(request, key):
    reg = _registry()
    entry = reg.get(key)
    if entry is None:
        from django.http import Http404
        raise Http404("Unknown setup page")
    if not has_role(request.user, *entry['roles']):
        from django.http import HttpResponseForbidden
        return None, HttpResponseForbidden("You do not have access to this page.")
    return entry, None


def _qs(entry, company):
    qs = entry['model'].objects.all()
    if entry.get('scoped', True) and hasattr(entry['model'], 'company'):
        qs = qs.filter(company=company)
    return qs


def _form_class(entry, company):
    if entry.get('form_class'):
        return entry['form_class']
    model = entry['model']
    widgets = {f.name: DATE for f in model._meta.fields if isinstance(f, dj_forms.fields.Field) is False and f.get_internal_type() == 'DateField' and f.name in entry['fields']}
    return modelform_factory(model, form=StyledModelForm, fields=entry['fields'], widgets=widgets)


def _limit_related(form, company):
    """Only offer the current company's records in dropdowns."""
    for f in form.fields.values():
        qs = getattr(f, 'queryset', None)
        if qs is None:
            continue
        # Rehumile's User also has a `company` (the client company) — only filter on HR's own Company.
        try:
            if qs.model._meta.get_field('company').related_model is type(company):
                f.queryset = qs.filter(company=company)
        except Exception:
            pass


@role_required(*HR_STAFF)
def crud_list(request, key):
    entry, denied = _entry(request, key)
    if denied:
        return denied
    company = current_company(request)
    objs = _qs(entry, company)
    cols = entry['cols']
    rows = [{'obj': o, 'cells': [getattr(o, c) if not callable(getattr(o, c)) else getattr(o, c)() for c in cols]} for o in objs]
    return render(request, 'hr/manage/crud_list.html', {
        'entry': entry, 'key': key, 'rows': rows, 'cols': [c.replace('_', ' ').capitalize() for c in cols], 'active': 'setup-' + key,
        'sections': [(k, v['title']) for k, v in _registry().items() if has_role(request.user, *v['roles'])]})


SETUP_INTRO = {
    'departments': "A department is a section of the business, such as Forecourt, Office or Tuck Shop. Only the name is required. "
                   "'Parent department' is optional: use it only when this department sits inside a bigger one (for example Night Shift inside Forecourt). "
                   "Leave it empty for a top-level department.",
    'blackouts': "A blackout period is a range of dates when leave cannot be taken, for example month-end or the December rush. "
                 "Leave requests that fall inside the dates are blocked. Pick the start and end dates and, if needed, the department it applies to; "
                 "leave the department empty to apply to everyone.",
    'positions': "A position is a job title, such as Pump Attendant or Cashier. Choose the department it belongs to; if the department is missing, use the + Add link beside it.",
}

FIELD_HELP = {
    'parent': "Optional. Only pick a larger department if this one sits inside it. Leave empty for a top-level department.",
    'department': "The department this belongs to. Missing? Use the + Add link.",
}


def _add_help(form, entry):
    for name, text in FIELD_HELP.items():
        f = form.fields.get(name)
        if f is not None and not f.help_text:
            f.help_text = text
            if name == 'parent':
                f.required = False


@role_required(*HR_STAFF)
def crud_edit(request, key, pk=None):
    entry, denied = _entry(request, key)
    if denied:
        return denied
    company = current_company(request)
    obj = get_object_or_404(_qs(entry, company), pk=pk) if pk else None
    old = model_to_dict(obj) if obj else None
    Form = _form_class(entry, company)
    form = Form(request.POST or None, request.FILES or None, instance=obj)
    _limit_related(form, company)
    _add_help(form, entry)
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = ''
    if request.method == 'POST' and form.is_valid():
        saved = form.save(commit=False)
        if hasattr(entry['model'], 'company') and getattr(saved, 'company_id', None) is None:
            saved.company = company
        for attr in ('changed_by', 'granted_by'):
            if hasattr(saved, attr) and getattr(saved, attr + '_id', 1) is None:
                setattr(saved, attr, request.user)
        if getattr(saved, 'compliance_basis', '') and hasattr(saved, 'compliance_acknowledged_by') and saved.compliance_acknowledged_by_id is None:
            saved.compliance_acknowledged_by = request.user
        saved.save()
        form.save_m2m()
        audit.log(f"{key}.{'update' if obj else 'create'}", 'setup', request=request, obj=saved,
                  old=old, new=model_to_dict(saved))
        messages.success(request, "Saved.")
        return redirect(next_url) if next_url else redirect('hr:manage_crud', key=key)
    quick_add = {}
    for name, f in form.fields.items():
        rel = getattr(getattr(f, 'queryset', None), 'model', None)
        k = next((k for k, e in _registry().items() if e['model'] is rel), None)
        if k and k != key:
            quick_add[name] = (k, _registry()[k]['title'])
    return render(request, 'hr/manage/crud_form.html', {'entry': entry, 'key': key, 'form': form, 'obj': obj, 'active': 'setup-' + key,
                                                        'quick_add': quick_add, 'next': request.get_full_path(), 'intro': SETUP_INTRO.get(key, '')})


@role_required(*HR_STAFF)
@require_POST
def crud_delete(request, key, pk):
    entry, denied = _entry(request, key)
    if denied:
        return denied
    obj = get_object_or_404(_qs(entry, current_company(request)), pk=pk)
    try:
        audit.log(f"{key}.delete", 'setup', request=request, obj=obj, old=model_to_dict(obj))
        obj.delete()
        messages.success(request, "Deleted.")
    except ProtectedError:
        messages.error(request, "That record is in use and cannot be deleted. Mark it inactive instead.")
    return redirect('hr:manage_crud', key=key)

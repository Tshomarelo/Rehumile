"""Leave rules: working-day counting, balances from the ledger, request
validation, the approval hooks, and the scheduled accrual / year-end runs."""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from ..models import (
    BlackoutPeriod, Employee, LeavePolicy, LeaveRequest, LeaveTransaction, LeaveType, PublicHoliday,
)
from . import audit, workflow
from .notify import notify

ZERO = Decimal('0')
HALF = Decimal('0.5')


def fmt(d):
    """10.0000 -> '10', 1.2500 -> '1.25' (for messages people read)."""
    return format(Decimal(d).quantize(Decimal('0.01')).normalize(), 'f')


# ------------------------------------------------------------ working days
def public_holiday_dates(company, start, end, site=None):
    qs = PublicHoliday.objects.filter(company=company, date__range=(start, end))
    dates = set()
    for h in qs:
        if h.site_id is None or (site is not None and h.site_id == site.pk):
            dates.add(h.date)
    return dates


def working_days(employee, start, end, half_start=False, half_end=False):
    """Working days in [start, end]: weekends (per the company's work week)
    and public holidays are not counted, and a half day at either end counts
    as 0.5."""
    if end < start:
        return ZERO
    company = employee.company
    work_days = company.work_day_numbers
    holidays = public_holiday_dates(company, start, end, employee.site)
    total = ZERO
    d = start
    while d <= end:
        if d.weekday() in work_days and d not in holidays:
            total += Decimal('1')
        d += timedelta(days=1)
    is_work = lambda day: day.weekday() in work_days and day not in holidays
    if start == end:
        if (half_start or half_end) and is_work(start):
            total = HALF
        return total
    if half_start and is_work(start):
        total -= HALF
    if half_end and is_work(end):
        total -= HALF
    return total


# ---------------------------------------------------------------- policies
def policy_for(employee):
    if employee.leave_policy_id:
        return employee.leave_policy
    return LeavePolicy.objects.filter(company=employee.company, is_default=True).first()


def leave_types_for(employee):
    policy = policy_for(employee)
    if policy is None:
        return LeaveType.objects.none()
    return policy.leave_types.filter(is_active=True).order_by('name')


# ---------------------------------------------------------------- balances
def balance_summary(employee, leave_type, on=None):
    """Accrued, taken, pending and available for one leave type, all from the
    ledger and the open requests."""
    txns = LeaveTransaction.objects.filter(employee=employee, leave_type=leave_type)
    if on:
        txns = txns.filter(date__lte=on)
    total = lambda **kw: txns.filter(**kw).aggregate(s=Sum('days'))['s'] or ZERO
    accrued = total(kind__in=['ACCRUAL', 'OPENING']) + total(kind='ADJUSTMENT', days__gt=0) + total(kind='EXPIRY') + total(kind='ADJUSTMENT', days__lt=0)
    taken = -(total(kind='USAGE') + total(kind='RESTORE'))
    balance = txns.aggregate(s=Sum('days'))['s'] or ZERO
    pending = LeaveRequest.objects.filter(
        employee=employee, leave_type=leave_type, status='PENDING', pending_action='APPLY'
    ).aggregate(s=Sum('days'))['s'] or ZERO
    return {
        'leave_type': leave_type, 'accrued': accrued, 'taken': taken, 'pending': pending,
        'balance': balance, 'available': balance - pending,
    }


def balances_for(employee):
    return [balance_summary(employee, lt) for lt in leave_types_for(employee)]


# -------------------------------------------------------------- validation
def validate_request(employee, leave_type, start, end, half_start=False, half_end=False,
                     has_attachment=False, ignore_request=None, hr_override=False):
    """Returns (days, errors). hr_override skips notice, blackout and document
    rules so HR can capture leave that was phoned in."""
    errors = []
    if end < start:
        return ZERO, ["The end date is before the start date."]
    if (half_start or half_end) and not leave_type.half_days_allowed:
        errors.append(f"{leave_type.name} cannot be taken in half days.")
    days = working_days(employee, start, end, half_start, half_end)
    if days <= 0:
        errors.append("There are no working days in the dates you chose (weekends, public holidays and days off are not counted).")
        return days, errors

    if not hr_override:
        notice = (start - timezone.localdate()).days
        if notice < leave_type.min_notice_days:
            errors.append(f"{leave_type.name} needs at least {leave_type.min_notice_days} days' notice.")
        blackouts = BlackoutPeriod.objects.filter(
            company=employee.company, start_date__lte=end, end_date__gte=start,
        )
        for b in blackouts:
            if (b.leave_type_id in (None, leave_type.pk)) and (b.department_id in (None, employee.department_id)):
                errors.append(f"Leave cannot be taken from {b.start_date} to {b.end_date}: {b.reason}.")
        limit = leave_type.attachment_required_over_days
        if limit is not None and days > limit and not has_attachment:
            errors.append(f"A supporting document (for example a medical certificate) is required for {leave_type.name} longer than {fmt(limit)} days.")

    overlapping = LeaveRequest.objects.filter(
        employee=employee, status__in=['PENDING', 'APPROVED', 'CANCEL_REQUESTED'],
        start_date__lte=end, end_date__gte=start,
    )
    if ignore_request is not None:
        overlapping = overlapping.exclude(pk=ignore_request.pk)
    if overlapping.exists():
        other = overlapping.first()
        errors.append(f"This overlaps another leave request ({other.start_date} to {other.end_date}, {other.get_status_display().lower()}).")

    if leave_type.is_paid:
        summary = balance_summary(employee, leave_type)
        allowance = summary['available'] + (leave_type.max_negative_days if leave_type.allow_negative else ZERO)
        if days > allowance:
            errors.append(f"Not enough {leave_type.name} leave: {fmt(summary['available'])} days available, {fmt(days)} requested.")
    return days, errors


# ----------------------------------------------------------------- requests
@transaction.atomic
def create_request(employee, leave_type, start, end, half_start, half_end, reason, attachment, submitter, captured_by=None):
    hr_override = captured_by is not None
    days, errors = validate_request(employee, leave_type, start, end, half_start, half_end,
                                    has_attachment=bool(attachment), hr_override=hr_override)
    if errors:
        return None, errors
    req = LeaveRequest.objects.create(
        employee=employee, leave_type=leave_type, start_date=start, end_date=end,
        half_day_start=half_start, half_day_end=half_end, days=days, reason=reason,
        attachment=attachment, captured_by=captured_by,
    )
    summary = f"{employee.display_name}: {leave_type.name} {start:%d %b} to {end:%d %b %Y} ({fmt(days)} days)"
    workflow.start(req, 'leave', submitter, employee, summary)
    audit.log('leave.request', 'leave', user=submitter, obj=req, employee=employee, new={
        'type': leave_type.name, 'start': start, 'end': end, 'days': days,
        'captured_by': captured_by.get_username() if captured_by else None,
    })
    return req, []


@transaction.atomic
def request_cancellation(req, user):
    """Cancel a pending request outright, or ask for an approved one to be
    cancelled (which goes back to the manager)."""
    inst = latest_instance(req)
    if req.status == 'PENDING':
        if inst is not None and inst.status == 'PENDING':
            workflow.withdraw(inst, user if user.pk == inst.submitter_id else inst.submitter)
        return
    if req.status == 'APPROVED':
        if req.start_date < timezone.localdate() and req.end_date < timezone.localdate():
            raise workflow.WorkflowError("Leave that has already been taken cannot be cancelled.")
        req.status = 'CANCEL_REQUESTED'
        req.pending_action = 'CANCEL'
        req.save(update_fields=['status', 'pending_action', 'updated_at'])
        summary = f"Cancel approved leave - {req.employee.display_name}: {req.leave_type.name} {req.start_date:%d %b} to {req.end_date:%d %b %Y}"
        workflow.start(req, 'leave', user, req.employee, summary)
        audit.log('leave.cancel_request', 'leave', user=user, obj=req, employee=req.employee)
        return
    raise workflow.WorkflowError("This request can no longer be cancelled.")


def latest_instance(req):
    from django.contrib.contenttypes.models import ContentType
    from ..models import WorkflowInstance
    return WorkflowInstance.objects.filter(
        content_type=ContentType.objects.get_for_model(LeaveRequest), object_id=req.pk
    ).order_by('-created_at').first()


# --------------------------------------------------------- approval hooks
def finalise_approved(req, instance):
    if req.pending_action == 'CANCEL':
        req.status = 'CANCELLED'
        req.pending_action = 'APPLY'
        req.save(update_fields=['status', 'pending_action', 'updated_at'])
        LeaveTransaction.objects.create(
            employee=req.employee, leave_type=req.leave_type, date=timezone.localdate(), kind='RESTORE',
            days=req.days, reason=f"Approved leave {req.start_date} to {req.end_date} cancelled", request=req)
        audit.log('leave.cancelled', 'leave', obj=req, employee=req.employee)
        from . import roster_db
        roster_db.on_leave_cancelled(req)
        return
    req.status = 'APPROVED'
    req.save(update_fields=['status', 'updated_at'])
    LeaveTransaction.objects.create(
        employee=req.employee, leave_type=req.leave_type, date=req.start_date, kind='USAGE',
        days=-req.days, reason=f"{req.leave_type.name} {req.start_date} to {req.end_date}", request=req)
    audit.log('leave.approved', 'leave', obj=req, employee=req.employee, new={'days': req.days})
    from . import roster_db
    roster_db.on_leave_approved(req)


def finalise_rejected(req, instance, reason):
    if req.pending_action == 'CANCEL':
        req.status = 'APPROVED'
        req.pending_action = 'APPLY'
    else:
        req.status = 'DECLINED'
    req.decision_note = reason
    req.save(update_fields=['status', 'pending_action', 'decision_note', 'updated_at'])


def finalise_withdrawn(req, instance):
    if req.pending_action == 'CANCEL':
        req.status = 'APPROVED'
        req.pending_action = 'APPLY'
    else:
        req.status = 'CANCELLED'
    req.save(update_fields=['status', 'pending_action', 'updated_at'])


# -------------------------------------------------------------- adjustments
@transaction.atomic
def adjust_balance(employee, leave_type, days, reason, user, kind='ADJUSTMENT'):
    if not (reason or '').strip():
        raise workflow.WorkflowError("A reason is required for a balance adjustment.")
    txn = LeaveTransaction.objects.create(
        employee=employee, leave_type=leave_type, kind=kind, days=days, reason=reason, created_by=user)
    audit.log('leave.adjust', 'leave', user=user, obj=txn, employee=employee,
              new={'type': leave_type.name, 'days': days, 'reason': reason}, sensitive=True)
    return txn


# ----------------------------------------------------- scheduled accrual runs
def _last_day(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def run_accruals(company, on_date=None, user=None):
    """Credit leave for the month (or the year, for 'annual' types in January).
    Safe to run repeatedly: each employee/type is credited once per period."""
    on_date = on_date or timezone.localdate()
    created = 0
    for emp in Employee.objects.filter(company=company).exclude(status='TERMINATED'):
        if emp.start_date and emp.start_date > _last_day(on_date):
            continue
        for lt in leave_types_for(emp):
            if lt.accrual_method == 'MONTHLY':
                amount, key = lt.monthly_accrual, on_date.strftime('%Y-%m')
            elif lt.accrual_method == 'ANNUAL' and on_date.month == 1:
                amount, key = lt.annual_days, str(on_date.year)
            else:
                continue
            if amount <= 0:
                continue
            if LeaveTransaction.objects.filter(employee=emp, leave_type=lt, kind='ACCRUAL', period_key=key).exists():
                continue
            LeaveTransaction.objects.create(
                employee=emp, leave_type=lt, date=on_date, kind='ACCRUAL', days=amount,
                reason=f"Accrual {key}", period_key=key, created_by=user)
            created += 1
    audit.log('leave.accrual_run', 'leave', user=user, description=f"{company}: {created} accruals for {on_date:%Y-%m}")
    return created


def run_year_end(company, year, user=None):
    """Carry over up to each type's limit and expire the rest as at 1 January
    of the following year. Idempotent."""
    expired = 0
    cutoff = date(year, 12, 31)
    for emp in Employee.objects.filter(company=company).exclude(status='TERMINATED'):
        for lt in leave_types_for(emp):
            if lt.carry_over_max is None:
                continue
            key = f"expiry-{year}"
            if LeaveTransaction.objects.filter(employee=emp, leave_type=lt, kind='EXPIRY', period_key=key).exists():
                continue
            balance = balance_summary(emp, lt, on=cutoff)['balance']
            excess = balance - lt.carry_over_max
            if excess > 0:
                LeaveTransaction.objects.create(
                    employee=emp, leave_type=lt, date=date(year + 1, 1, 1), kind='EXPIRY', days=-excess,
                    reason=f"{excess} days above the carry-over limit of {lt.carry_over_max} expired", period_key=key, created_by=user)
                expired += 1
    audit.log('leave.year_end_run', 'leave', user=user, description=f"{company}: {expired} balances expired for {year}")
    return expired


# ------------------------------------------------------------------ calendar
def team_calendar(company, start, end, department=None, visible_employees=None):
    """Approved and pending leave overlapping [start, end], for the team
    calendar."""
    qs = LeaveRequest.objects.filter(
        employee__company=company, status__in=['APPROVED', 'PENDING', 'CANCEL_REQUESTED'],
        start_date__lte=end, end_date__gte=start,
    ).select_related('employee', 'leave_type')
    if department is not None:
        qs = qs.filter(employee__department=department)
    if visible_employees is not None:
        qs = qs.filter(employee__in=visible_employees)
    return qs

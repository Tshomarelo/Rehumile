"""Salary master data (Section 2): effective-dated, approved by a second person, visible only to permitted roles."""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from ..models import (HR_ADMIN, PAYROLL_ADMIN, SUPER_ADMIN, Employee, HRSettings, SalaryLine, SalaryRecord)
from . import audit, workflow
from .access import has_role


class SalaryError(Exception):
    pass


def get_pay_settings(company):
    return HRSettings.objects.get_or_create(company=company)[0]


def can_see_salaries(user):
    """SM-5: managers do not see salaries by default; an employee sees pay through payslips."""
    return has_role(user, HR_ADMIN, PAYROLL_ADMIN, SUPER_ADMIN)


def mask(value):
    return "R ••••••" if value is not None else "-"


def current_record(employee, on=None):
    on = on or timezone.localdate()
    return (SalaryRecord.objects.filter(employee=employee, status='APPROVED', start_date__lte=on)
            .filter(models_q_open(on)).order_by('-start_date', '-id').first())


def models_q_open(on):
    from django.db.models import Q
    return Q(end_date__isnull=True) | Q(end_date__gte=on)


def history(employee):
    return list(SalaryRecord.objects.filter(employee=employee).select_related('captured_by', 'approved_by'))


def increase_percent(prev, amount):
    if prev is None or not prev.amount:
        return Decimal('0')
    return ((Decimal(amount) - prev.amount) / prev.amount * 100).quantize(Decimal('0.1'))


@transaction.atomic
def capture_change(employee, user, pay_type, amount, start_date, reason='', frequency='MONTHLY', lines=()):
    """SM-4: HR Admin captures; Payroll Admin approves (a different person); big increases also need senior management."""
    if not has_role(user, HR_ADMIN, SUPER_ADMIN):
        raise SalaryError("Only HR Admin can capture a salary change.")
    try:
        amount = Decimal(str(amount))
    except InvalidOperation:
        raise SalaryError("Enter the amount as a number.")
    if amount <= 0:
        raise SalaryError("The amount must be more than zero.")
    prev = current_record(employee, start_date)
    latest = SalaryRecord.objects.filter(employee=employee, status='APPROVED').order_by('-start_date').first()
    if latest and start_date <= latest.start_date:
        raise SalaryError(f"A change must start after the current record began on {latest.start_date}. Salary history is never edited in place.")
    if SalaryRecord.objects.filter(employee=employee, status='PENDING').exists():
        raise SalaryError("There is already a salary change waiting for approval for this person.")
    pct = increase_percent(prev, amount)
    settings = get_pay_settings(employee.company)
    key = 'salary_change_large' if pct > settings.increase_needs_senior_pct else 'salary_change'
    rec = SalaryRecord.objects.create(employee=employee, pay_type=pay_type, amount=amount, frequency=frequency, start_date=start_date,
                                      reason=reason[:250], captured_by=user, previous=prev)
    for ln in lines:
        SalaryLine.objects.create(salary=rec, name=ln['name'], kind=ln.get('kind', 'ALLOWANCE'), amount=Decimal(str(ln['amount'])),
                                  start_date=ln.get('start_date'), end_date=ln.get('end_date'))
    audit.log('salary.capture', 'salary', user=user, obj=rec, employee=employee, sensitive=True,
              new={'pay_type': pay_type, 'start': start_date, 'increase_pct': str(pct)})
    workflow.start(rec, key, user, employee, f"Salary change for {employee.display_name} from {start_date}"
                   + (f" (increase {pct}%, needs senior approval)" if key == 'salary_change_large' else ''))
    return rec


@transaction.atomic
def finalise_approved(rec, instance):
    """Approved: close the previous record the day before, and queue the sync."""
    rec.status = 'APPROVED'
    last = instance.steps.filter(status='APPROVED').order_by('-acted_at').first()
    rec.approved_by = last.acted_by if last else None
    prev = SalaryRecord.objects.filter(employee=rec.employee, status='APPROVED').exclude(pk=rec.pk) \
        .filter(start_date__lt=rec.start_date).order_by('-start_date').first()
    if prev and (prev.end_date is None or prev.end_date >= rec.start_date):
        prev.end_date = rec.start_date - timedelta(days=1)
        prev.save(update_fields=['end_date'])
    settings = get_pay_settings(rec.employee.company)
    rec.sync_status = 'PENDING' if settings.salary_sync_enabled else 'NA'
    rec.save()
    audit.log('salary.approved', 'salary', obj=rec, employee=rec.employee, sensitive=True, new={'start': rec.start_date})
    if rec.start_date <= timezone.localdate():
        from . import sync
        sync.sync_salary(rec)


def salary_report(company, start=None, end=None):
    """Salary changes: every change with approver and effective date."""
    qs = SalaryRecord.objects.filter(employee__company=company).select_related('employee', 'captured_by', 'approved_by')
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    return qs


def import_csv(company, text, user, apply=False):
    """SM-7: first import with a check report showing new, changed and rejected rows before anything is saved."""
    settings = get_pay_settings(company)
    report, ready = [], []
    for i, row in enumerate(csv.DictReader(io.StringIO(text.lstrip('﻿'))), start=2):
        num = (row.get('employee_number') or '').strip()
        emp = Employee.objects.filter(company=company, employee_number=num).first()
        problems = []
        if emp is None:
            problems.append(f"employee {num!r} not found")
        try:
            amount = Decimal((row.get('amount') or '').replace(',', '').strip())
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            amount = None
            problems.append("amount is not a positive number")
        pay_type = (row.get('pay_type') or 'MONTHLY').strip().upper()
        if pay_type not in dict(SalaryRecord.PAY_TYPES):
            problems.append(f"pay_type {pay_type!r} not valid")
        try:
            start = date.fromisoformat((row.get('start_date') or '').strip())
        except ValueError:
            start = None
            problems.append("start_date must be YYYY-MM-DD")
        if problems:
            report.append({'line': i, 'number': num, 'status': 'rejected', 'detail': '; '.join(problems)})
            continue
        cur = current_record(emp, start)
        if cur is None:
            report.append({'line': i, 'number': num, 'status': 'new', 'detail': f"{pay_type} from {start}"})
        elif cur.amount == amount and cur.pay_type == pay_type:
            report.append({'line': i, 'number': num, 'status': 'unchanged', 'detail': 'same as the current record'})
            continue
        else:
            report.append({'line': i, 'number': num, 'status': 'changed', 'detail': f"increase {increase_percent(cur, amount)}%"})
        ready.append((emp, pay_type, amount, start, (row.get('frequency') or 'MONTHLY').strip().upper()))
    if apply and not [r for r in report if r['status'] == 'rejected']:
        if not has_role(user, SUPER_ADMIN):
            raise SalaryError("Only a Super Admin can load salaries in bulk. Everyone else captures changes one by one for approval.")
        with transaction.atomic():
            for emp, pay_type, amount, start, freq in ready:
                latest = SalaryRecord.objects.filter(employee=emp, status='APPROVED').order_by('-start_date').first()
                if latest and start <= latest.start_date:
                    raise SalaryError(f"{emp.employee_number}: start date must be after {latest.start_date}.")
                rec = SalaryRecord.objects.create(employee=emp, pay_type=pay_type, amount=amount, frequency=freq if freq in dict(SalaryRecord.FREQUENCY) else 'MONTHLY',
                                                  start_date=start, reason='Initial load from spreadsheet', status='APPROVED', captured_by=user,
                                                  approved_by=user, previous=latest, sync_status='PENDING' if settings.salary_sync_enabled else 'NA')
                if latest and (latest.end_date is None or latest.end_date >= start):
                    latest.end_date = start - timedelta(days=1)
                    latest.save(update_fields=['end_date'])
                audit.log('salary.import', 'salary', user=user, obj=rec, employee=emp, sensitive=True,
                          description='Bulk load approved by the importing Super Admin')
    return report

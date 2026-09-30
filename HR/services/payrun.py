"""Payruns: the totals per person from your payroll tool, advance recoveries, locking, and the sync trigger."""
import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from ..models import Employee, PayPeriod, PayrunLine, PayrunRun, PAYROLL_ADMIN, SUPER_ADMIN
from . import advances, audit, salary, sync
from .access import has_role
from .notify import notify


class PayrunError(Exception):
    pass


def get_run(period, user=None):
    run, created = PayrunRun.objects.get_or_create(pay_period=period)
    if created:
        audit.log('payrun.create', 'payroll', user=user, obj=run, sensitive=True)
    return run


def _dec(v):
    try:
        return Decimal(str(v).replace(',', '').strip() or '0')
    except InvalidOperation:
        raise PayrunError(f"{v!r} is not a number.")


@transaction.atomic
def import_lines(run, text, user):
    """Load per-person totals exported from the payroll tool. Columns: employee_number, gross, other_deductions, net."""
    if run.status == 'LOCKED':
        raise PayrunError("This payrun is locked.")
    company = run.pay_period.company
    made, problems = 0, []
    for i, row in enumerate(csv.DictReader(io.StringIO(text.lstrip('﻿'))), start=2):
        num = (row.get('employee_number') or '').strip()
        emp = Employee.objects.filter(company=company, employee_number=num).first()
        if emp is None:
            problems.append(f"line {i}: employee {num!r} not found")
            continue
        try:
            gross, other = _dec(row.get('gross')), _dec(row.get('other_deductions'))
            net = _dec(row.get('net')) if (row.get('net') or '').strip() else gross - other
        except PayrunError as e:
            problems.append(f"line {i}: {e}")
            continue
        PayrunLine.objects.update_or_create(run=run, employee=emp, defaults={
            'gross': gross, 'other_deductions': other, 'net': net, 'advance_recovery': Decimal('0'),
            'company_cost': _dec(row.get('company_cost')) if (row.get('company_cost') or '').strip() else None})
        made += 1
    audit.log('payrun.import', 'payroll', user=user, obj=run, sensitive=True, new={'lines': made, 'problems': len(problems)})
    return made, problems


def preview_recoveries(run):
    """RC-3: show what locking will deduct, per person, before it happens."""
    rows = []
    for line in run.lines.select_related('employee'):
        plan = advances.plan_recoveries(line.employee, line.gross, line.net)
        total = sum((a for _, _, a in plan), Decimal('0'))
        if total > 0 or plan:
            rows.append({'line': line, 'total': total, 'items': [(adv, amt) for adv, _, amt in plan],
                         'net_after': line.net - total})
    return rows


@transaction.atomic
def lock(run, user):
    """Lock the payrun: take the scheduled advance recoveries (payslip shows them), then sync to the reconciliation system."""
    if not has_role(user, PAYROLL_ADMIN, SUPER_ADMIN):
        raise PayrunError("Only Payroll Admin can lock a payrun.")
    if run.status == 'LOCKED':
        raise PayrunError("This payrun is already locked.")
    if not run.lines.exists():
        raise PayrunError("Import the payrun totals first.")
    total = Decimal('0')
    for line in run.lines.select_related('employee'):
        rec = advances.apply_recoveries(line, run, user)
        line.advance_recovery = rec
        line.net = line.net - rec
        line.save()
        total += rec
    run.status, run.locked_by, run.locked_at = 'LOCKED', user, timezone.now()
    run.save()
    audit.log('payrun.lock', 'payroll', user=user, obj=run, sensitive=True, new={'recovered': str(total)})
    result = sync.sync_payrun(run, user)
    return total, result


def payslip_advance_info(employee, pay_period):
    """LK-7: the payslip's advance recovery line and remaining balance."""
    line = PayrunLine.objects.filter(employee=employee, run__pay_period=pay_period, run__status='LOCKED').first()
    if line is None:
        return None
    return {'recovery': line.advance_recovery, 'balance': advances.outstanding_balance(employee), 'gross': line.gross, 'net': line.net}

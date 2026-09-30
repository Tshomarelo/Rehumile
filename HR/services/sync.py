"""One-way sync from the HR system to the reconciliation system (Section 3).

* The HR value always wins (SY-1). Employees are matched by employee number only, never guessed (SY-2).
* Every overwrite records old and new value (SY-4). Running it twice changes nothing (SY-7).
* A closed accounting period is never rewritten: an adjustment is proposed for finance to approve (SY-6).
* Until the go-live switch is on, nothing is written: the reports show what would change (SY-11).
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from ..models import (AdjustmentEntry, Employee, HR_ADMIN, PAYROLL_ADMIN, PayrunLine, SUPER_ADMIN, SalaryRecord, SyncLink, SyncLog)
from . import audit, recon_bridge, salary
from .notify import notify


def ensure_link(employee):
    """Existing link, or a match by employee number. None = not matched (listed for an administrator)."""
    link = SyncLink.objects.filter(employee=employee).first()
    if link:
        return link
    ref = recon_bridge.find_person(employee.employee_number)
    if ref:
        return SyncLink.objects.create(employee=employee, kind='MATCHED', recon_ref=ref, matched_by='employee number')
    return None


def mark_no_counterpart(employee, user):
    """An administrator states that this person has no reconciliation counterpart (for example office staff)."""
    link, _ = SyncLink.objects.update_or_create(employee=employee, defaults={'kind': 'NO_COUNTERPART', 'recon_ref': '', 'matched_by': f"set by {user.get_username()}"})
    audit.log('sync.no_counterpart', 'sync', user=user, obj=link, employee=employee)
    return link


def link_manually(employee, ref, user):
    """An administrator links a person to a reconciliation reference. The reference must exist there."""
    if recon_bridge.find_person(ref) is None:
        raise ValueError("The reconciliation system is not connected to Rehumile, so people cannot be linked to it.")
    link, _ = SyncLink.objects.update_or_create(employee=employee, defaults={'kind': 'MATCHED', 'recon_ref': ref, 'matched_by': f"set by {user.get_username()}"})
    audit.log('sync.link', 'sync', user=user, obj=link, employee=employee, new={'ref': ref})
    return link


def unmatched(company):
    """SY-2: everyone in HR who cannot be matched (nothing is overwritten for them)."""
    out = []
    for e in Employee.objects.filter(company=company, status='ACTIVE'):
        if SyncLink.objects.filter(employee=e).exists():
            continue
        if recon_bridge.find_person(e.employee_number):
            continue
        out.append(e)
    return out


def _log(kind, key, status, employee=None, target='', target_id=None, old='', new='', message=''):
    return SyncLog.objects.create(kind=kind, source_key=key, employee=employee, target=target, target_id=target_id,
                                  old_value=str(old), new_value=str(new), status=status, message=message[:300])


def _basis_amount(line, basis):
    if basis == 'NET':
        return line.net
    if basis == 'COST' and line.company_cost is not None:
        return line.company_cost
    return line.gross


def _alert(company, message):
    """SY-8: Payroll Admin and Super Admin are told when a sync fails."""
    from .workflow import _role_holders
    users = list(_role_holders(PAYROLL_ADMIN)) + list(_role_holders(SUPER_ADMIN))
    notify(users, 'sync', "Salary sync problem", message, reverse('hr:manage_sync'))


def sync_payrun(run, user=None):
    """SY-3: when a payrun is locked, write each person's total as a Salaries expense entry."""
    company = run.pay_period.company
    ps = salary.get_pay_settings(company)
    result = {'created': 0, 'updated': 0, 'unchanged': 0, 'unmatched': 0, 'adjusted': 0, 'failed': 0, 'skipped': 0}
    if not ps.salary_sync_enabled:
        _log('SALARIES_EXPENSE', f"PAYRUN:{run.pk}", 'SKIPPED', message="Sync is not switched on; see the first-load report")
        result['skipped'] = run.lines.count()
        return result
    day = run.pay_period.pay_date or run.pay_period.end_date
    for line in run.lines.select_related('employee'):
        emp = line.employee
        key = f"PAYRUN:{run.pk}:{emp.employee_number}"
        link = ensure_link(emp)
        if link is None:
            _log('SALARIES_EXPENSE', key, 'UNMATCHED', emp, message="No reconciliation person with this employee number; nothing overwritten")
            result['unmatched'] += 1
            continue
        amount = _basis_amount(line, ps.sync_amount_basis)
        prev = SyncLog.objects.filter(source_key=key, status__in=('OK', 'NOCHANGE')).exclude(target_id=None).order_by('-id').first()
        try:
            with transaction.atomic():
                desc = f"{emp.display_name} ({emp.employee_number}) salary {run.pay_period.label} [HR payrun {run.pk}]"
                if prev is not None:
                    old = recon_bridge.expense_amount(prev.target_id)
                    if old is not None and old == amount:
                        result['unchanged'] += 1
                        continue
                    if ps.books_closed_through and day <= ps.books_closed_through:
                        _propose_adjustment(ps, emp, run, key, day, amount - (old or 0))
                        result['adjusted'] += 1
                        continue
                    eid, old_amt = recon_bridge.salaries_expense(desc, amount, day, user, ps.salaries_category, existing_id=prev.target_id)
                    _log('SALARIES_EXPENSE', key, 'OK', emp, 'BusinessExpense', eid, old_amt if old_amt is not None else '', amount, "Overwritten from the HR payrun")
                    result['updated'] += 1
                    continue
                if ps.books_closed_through and day <= ps.books_closed_through:
                    _propose_adjustment(ps, emp, run, key, day, amount)
                    result['adjusted'] += 1
                    continue
                eid, _ = recon_bridge.salaries_expense(desc, amount, day, user, ps.salaries_category)
                _log('SALARIES_EXPENSE', key, 'OK', emp, 'BusinessExpense', eid, '', amount, "Created from the locked payrun")
                result['created'] += 1
        except Exception as e:  # noqa - one bad person must not stop the rest; it is logged and alerted (SY-8)
            _log('SALARIES_EXPENSE', key, 'FAILED', emp, message=f"{type(e).__name__}: {e}")
            result['failed'] += 1
    if result['failed']:
        _alert(company, f"{result['failed']} salary line(s) failed to sync for payrun {run.pay_period.label}. See the sync log.")
    audit.log('sync.payrun', 'sync', user=user, obj=run, sensitive=True, new=result)
    return result


def _propose_adjustment(ps, emp, run, key, day, difference):
    """SY-6: the period is closed. Do not touch it; propose an adjustment in the open period."""
    if AdjustmentEntry.objects.filter(source_key=key, status='PENDING').exists():
        return
    AdjustmentEntry.objects.create(source_key=key, employee=emp, period_label=run.pay_period.label, original_date=day, difference=difference)
    _log('SALARIES_EXPENSE', key, 'ADJUSTMENT', emp, new=difference, message=f"Period closed through {ps.books_closed_through}: adjustment proposed for finance")


@transaction.atomic
def resolve_adjustment(adj, user, approve):
    """A finance user approves: the difference is booked on the first open day; nothing closed is rewritten."""
    ps = salary.get_pay_settings(adj.employee.company)
    if adj.status != 'PENDING':
        raise ValueError("Already decided.")
    adj.decided_by = user
    if approve:
        day = (ps.books_closed_through + timedelta(days=1)) if ps.books_closed_through else timezone.localdate()
        eid, _ = recon_bridge.salaries_expense(f"Adjustment {adj.period_label}: {adj.employee.display_name} ({adj.employee.employee_number}) [{adj.source_key}]",
                                               adj.difference, day, user, ps.salaries_category)
        adj.recon_expense_id, adj.status = eid, 'APPROVED'
        _log('SALARIES_EXPENSE', adj.source_key + ':ADJ', 'OK', adj.employee, 'BusinessExpense', eid, '', adj.difference, 'Adjustment approved by finance')
    else:
        adj.status = 'REJECTED'
    adj.save()
    audit.log('sync.adjustment', 'sync', user=user, obj=adj, sensitive=True, new={'approved': approve})


def sync_salary(rec):
    """Rate sync (SY-3). The reconciliation system stores no per-person salary field, so the approved rate is published
    read-only through hr_salary_rate(); the log records that fact."""
    emp = rec.employee
    ps = salary.get_pay_settings(emp.company)
    if not ps.salary_sync_enabled:
        return 'NA'
    link = ensure_link(emp)
    if link is None:
        rec.sync_status, rec.sync_note = 'UNMATCHED', 'No reconciliation person with this employee number'
        rec.save(update_fields=['sync_status', 'sync_note'])
        _log('RATE', f"SALARY:{rec.pk}", 'UNMATCHED', emp, message=rec.sync_note)
        return 'UNMATCHED'
    rec.sync_status, rec.sync_note = 'SYNCED', 'Published read-only to the reconciliation system'
    rec.save(update_fields=['sync_status', 'sync_note'])
    _log('RATE', f"SALARY:{rec.pk}", 'OK', emp, 'salary rate', rec.pk, '', '(masked)', rec.sync_note)
    return 'SYNCED'


def sync_due_salaries():
    """Nightly: salary changes whose effective date has arrived."""
    n = 0
    for rec in SalaryRecord.objects.filter(status='APPROVED', sync_status='PENDING', start_date__lte=timezone.localdate()):
        sync_salary(rec)
        n += 1
    return n


def retry_failed(user=None):
    """SY-8: failed lines are retried by re-running the sync for their payrun."""
    from ..models import PayrunRun
    n = 0
    for key in SyncLog.objects.filter(status='FAILED').values_list('source_key', flat=True).distinct():
        parts = key.split(':')
        if parts[0] == 'PAYRUN' and len(parts) == 3:
            run = PayrunRun.objects.filter(pk=parts[1], status='LOCKED').first()
            if run:
                sync_payrun(run, user)
                n += 1
    return n


def hr_salary_rate(employee_number, on=None):
    """Read-only access for the reconciliation system: the approved rate for a person on a date (SM-9)."""
    emp = Employee.objects.filter(employee_number=employee_number).first()
    rec = salary.current_record(emp, on) if emp else None
    return (rec.amount, rec.pay_type) if rec else None


# ------------------------------------------------------------------ reports (SY-9, SY-11)
def daily_comparison(company):
    """Every person whose entry in the reconciliation system differs from the HR payrun figure."""
    ps = salary.get_pay_settings(company)
    rows = []
    for line in PayrunLine.objects.filter(run__status='LOCKED', employee__company=company).select_related('employee', 'run__pay_period'):
        key = f"PAYRUN:{line.run_id}:{line.employee.employee_number}"
        log = SyncLog.objects.filter(source_key=key, status__in=('OK', 'NOCHANGE')).exclude(target_id=None).order_by('-id').first()
        hr_amount = _basis_amount(line, ps.sync_amount_basis)
        recon = recon_bridge.expense_amount(log.target_id) if log else None
        if recon is None or recon != hr_amount:
            rows.append({'employee': line.employee, 'period': line.run.pay_period, 'hr': hr_amount, 'recon': recon,
                         'difference': hr_amount - (recon or Decimal('0'))})
    return rows


def first_load_report(company, months=6):
    """SY-11: what the reconciliation system holds as Salaries today against the HR figures, before anything is overwritten."""
    from ..models import PayPeriod
    ps = salary.get_pay_settings(company)
    rows = []
    for p in PayPeriod.objects.filter(company=company).order_by('-start_date')[:months]:
        existing = recon_bridge.existing_salary_total(ps.salaries_category, p.start_date, p.end_date)
        hr_total = sum((_basis_amount(l, ps.sync_amount_basis) for l in PayrunLine.objects.filter(run__pay_period=p)), Decimal('0'))
        rows.append({'period': p, 'recon_total': existing, 'hr_total': hr_total, 'difference': hr_total - existing,
                     'has_payrun': PayrunLine.objects.filter(run__pay_period=p).exists()})
    return rows


def totals_reconciliation(company):
    """LK-6: payrun totals in HR against the Salaries expense in the reconciliation system, month by month."""
    return first_load_report(company, 12)

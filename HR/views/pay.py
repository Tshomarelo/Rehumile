"""Salary, advance, payrun and sync pages."""
import csv
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import (
    ADVANCE_PAYER, HR_ADMIN, LINE_MANAGER, PAYROLL_ADMIN, SENIOR_MANAGER, SUPER_ADMIN, AdjustmentEntry, Advance, Employee,
    HRSettings, PayPeriod, PayrunRun, SalaryRecord, SyncLog,
)
from ..services import advances as A, audit, payrun as P, recon_bridge, salary as S, sync as Y
from ..services.access import current_company, employee_for, has_role, portal_required, role_required
from ..services.advances import AdvanceError
from ..services.payrun import PayrunError
from ..services.salary import SalaryError

HR_PAY = role_required(HR_ADMIN, PAYROLL_ADMIN, SUPER_ADMIN)
PAYROLL_ONLY = role_required(PAYROLL_ADMIN, SUPER_ADMIN)
PAYER = role_required(ADVANCE_PAYER, HR_ADMIN, PAYROLL_ADMIN, SUPER_ADMIN, LINE_MANAGER, SENIOR_MANAGER)
CAPTURER = role_required(LINE_MANAGER, HR_ADMIN, SUPER_ADMIN, ADVANCE_PAYER)


def _date(v):
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def _meta(request):
    return request.META.get('REMOTE_ADDR') or None, request.META.get('HTTP_USER_AGENT', '')


# ================================================================== employee: advances
@portal_required
def advances(request):
    emp = employee_for(request.user)
    if request.method == 'POST':
        try:
            adv = A.capture_request(emp, request.POST.get('amount'), request.POST.get('reason', ''), _date(request.POST.get('needed_by')),
                                    int(request.POST.get('payruns') or 1), request.user)
            messages.success(request, f"Request {adv.number} created. Enter the confirmation code we sent you to continue.")
        except (AdvanceError, ValueError) as e:
            messages.error(request, str(e))
        return redirect('hr:advances')
    st = A.eligibility(emp)
    mine = emp.advances.all()[:20]
    for a in mine:
        a.bal = a.balance
    return render(request, 'hr/advances.html', {'st': st, 'advances': mine, 'active': 'advances', 'emp': emp,
                                                'agreement': S.get_pay_settings(emp.company).agreement_text})


@portal_required
@require_POST
def advance_confirm(request, pk):
    emp = employee_for(request.user)
    adv = get_object_or_404(Advance, pk=pk, employee=emp)
    ip, dev = _meta(request)
    try:
        A.confirm_advance(adv, code=request.POST.get('code') or None, signed_name=request.POST.get('signed_name') or None,
                          actor=request.user, ip=ip, device=dev)
        messages.success(request, "Confirmed. Your request has gone for approval.")
    except AdvanceError as e:
        messages.error(request, str(e))
    return redirect('hr:advances')


@portal_required
@require_POST
def advance_resend(request, pk):
    emp = employee_for(request.user)
    adv = get_object_or_404(Advance, pk=pk, employee=emp, status='REQUESTED')
    A.issue_code(adv)
    messages.success(request, "A new code was sent.")
    return redirect('hr:advances')


@portal_required
@require_POST
def advance_cancel(request, pk):
    emp = employee_for(request.user)
    adv = get_object_or_404(Advance, pk=pk, employee=emp)
    try:
        A.cancel_advance(adv, request.user)
        messages.success(request, "Cancelled.")
    except AdvanceError as e:
        messages.error(request, str(e))
    return redirect('hr:advances')


# ================================================================== counter capture, payment (managers / payers)
@CAPTURER
def advance_capture(request):
    """AD-4: a manager, HR or supervisor captures the request for someone at the counter; the employee confirms it."""
    company = current_company(request)
    emp, st, q = None, None, (request.GET.get('q') or request.POST.get('q') or '').strip()
    if q:
        from django.db.models import Q
        emp = Employee.objects.filter(Q(employee_number__iexact=q) | Q(known_as__icontains=q) | Q(surname__icontains=q), company=company, status='ACTIVE').first()
        if emp:
            st = A.eligibility(emp)
    if request.method == 'POST' and emp and request.POST.get('do') == 'capture':
        try:
            adv = A.capture_request(emp, request.POST.get('amount'), request.POST.get('reason', ''), None, int(request.POST.get('payruns') or 1), request.user,
                                    emergency=bool(request.POST.get('emergency')), emergency_reason=request.POST.get('emergency_reason', ''))
            messages.success(request, f"{adv.number} captured. A one-time code was sent to {emp.display_name}'s phone. Ask them for it and enter it below.")
            return redirect('hr:manage_advance_detail', adv.pk)
        except (AdvanceError, ValueError) as e:
            messages.error(request, str(e))
    return render(request, 'hr/manage/advance_capture.html', {'q': q, 'emp': emp, 'st': st, 'active': 'advances'})


@PAYER
def advance_list(request):
    company = current_company(request)
    scope = request.GET.get('show', 'pay')
    qs = Advance.objects.filter(employee__company=company).select_related('employee')
    if not has_role(request.user, HR_ADMIN, PAYROLL_ADMIN, SUPER_ADMIN, ADVANCE_PAYER, SENIOR_MANAGER):
        from ..services.access import team_of
        qs = qs.filter(employee__in=team_of(request.user))            # RC-10: a manager sees their own team
    if scope == 'pay':
        qs = qs.filter(status='APPROVED')
    elif scope == 'open':
        qs = qs.filter(status__in=('PAID', 'RECOVERING'))
    elif scope == 'waiting':
        qs = qs.filter(status__in=('REQUESTED', 'AWAITING_APPROVAL'))
    rows = list(qs[:100])
    for a in rows:
        a.bal = a.balance
    return render(request, 'hr/manage/advances.html', {'advances': rows, 'scope': scope, 'flags': A.unpaid_flags(company),
                                                       'can_pay': has_role(request.user, ADVANCE_PAYER, SUPER_ADMIN), 'active': 'advances'})


@PAYER
def advance_detail(request, pk):
    adv = get_object_or_404(Advance.objects.select_related('employee'), pk=pk, employee__company=current_company(request))
    ps = S.get_pay_settings(adv.employee.company)
    return render(request, 'hr/manage/advance_detail.html', {
        'adv': adv, 'bal': adv.balance, 'ledger': adv.ledger.all(), 'schedule': adv.schedule.all(), 'confirmations': adv.confirmations.all(),
        'tills': recon_bridge.open_till_shifts() if ps.post_advances_to_reconciliation else [], 'funds': recon_bridge.petty_funds() if ps.post_advances_to_reconciliation else [],
        'can_pay': has_role(request.user, ADVANCE_PAYER, SUPER_ADMIN), 'is_admin': has_role(request.user, HR_ADMIN, SUPER_ADMIN),
        'active': 'advances'})


@PAYER
@require_POST
def advance_action(request, pk):
    adv = get_object_or_404(Advance, pk=pk, employee__company=current_company(request))
    act = request.POST.get('action')
    ip, dev = _meta(request)
    try:
        if act == 'confirm':
            A.confirm_advance(adv, code=request.POST.get('code'), actor=request.user, ip=ip, device=dev)
            messages.success(request, "Confirmed by the employee's code and sent for approval.")
        elif act == 'pay':
            pay = A.pay_advance(adv, request.user, request.POST.get('method'), shift_id=request.POST.get('shift') or None,
                                fund_id=request.POST.get('fund') or None, reference=request.POST.get('reference', ''))
            messages.success(request, f"Paid. Receipt {pay.receipt_number}.")
            return redirect('hr:manage_advance_receipt', adv.pk)
        elif act == 'repay':
            A.record_repayment(adv, request.POST.get('amount'), request.POST.get('method'), request.user,
                               shift_id=request.POST.get('shift') or None, fund_id=request.POST.get('fund') or None,
                               reference=request.POST.get('reference', ''))
            messages.success(request, "Repayment recorded.")
        elif act == 'cancel':
            A.cancel_advance(adv, request.user)
            messages.success(request, "Cancelled.")
        elif act == 'writeoff':
            A.request_writeoff(adv, request.user, request.POST.get('reason', ''))
            messages.success(request, "Write-off sent to senior management for approval.")
        elif act == 'final_pay':
            A.record_final_pay_agreement(adv, request.user, request.POST.get('note', ''))
            messages.success(request, "Final pay deduction agreement recorded.")
        elif act == 'resend':
            A.issue_code(adv)
            messages.success(request, "A new code was sent to the employee.")
    except (AdvanceError, ValueError) as e:
        messages.error(request, str(e))
    return redirect('hr:manage_advance_detail', adv.pk)


@PAYER
def advance_receipt(request, pk):
    adv = get_object_or_404(Advance.objects.select_related('employee'), pk=pk, employee__company=current_company(request))
    return render(request, 'hr/manage/advance_receipt.html', {'adv': adv, 'payment': getattr(adv, 'payment', None)})


# ================================================================== salaries
@HR_PAY
def salaries(request):
    company = current_company(request)
    emps = Employee.objects.filter(company=company, status='ACTIVE').order_by('surname')
    rows = []
    for e in emps:
        rec = S.current_record(e)
        rows.append({'e': e, 'rec': rec, 'pending': SalaryRecord.objects.filter(employee=e, status='PENDING').exists()})
    return render(request, 'hr/manage/salaries.html', {'rows': rows, 'active': 'pay', 'can_capture': has_role(request.user, HR_ADMIN, SUPER_ADMIN),
                                                       'revealed': request.session.pop('hr_salary_reveal', None)})


@HR_PAY
@require_POST
def salary_reveal(request, pk):
    """CT-6: amounts are masked; viewing one is logged."""
    emp = get_object_or_404(Employee, pk=pk, company=current_company(request))
    rec = S.current_record(emp)
    audit.log('salary.view', 'salary', request=request, obj=rec or emp, employee=emp, sensitive=True, description='Revealed a salary amount')
    request.session['hr_salary_reveal'] = {'employee': emp.pk, 'text': f"{emp.display_name}: {rec.get_pay_type_display()} R{rec.amount:,.2f}" if rec else f"{emp.display_name}: no salary record"}
    return redirect('hr:manage_salaries')


@HR_PAY
def salary_history(request, pk):
    emp = get_object_or_404(Employee, pk=pk, company=current_company(request))
    audit.log('salary.history', 'salary', request=request, obj=emp, employee=emp, sensitive=True, description='Viewed salary history')
    return render(request, 'hr/manage/salary_history.html', {'emp': emp, 'history': S.history(emp), 'active': 'pay'})


@role_required(HR_ADMIN, SUPER_ADMIN)
def salary_capture(request, pk):
    emp = get_object_or_404(Employee, pk=pk, company=current_company(request))
    cur = S.current_record(emp)
    if request.method == 'POST':
        try:
            rec = S.capture_change(emp, request.user, request.POST.get('pay_type', 'MONTHLY'), request.POST.get('amount'),
                                   _date(request.POST.get('start_date')) or timezone.localdate(), request.POST.get('reason', ''),
                                   request.POST.get('frequency', 'MONTHLY'))
            messages.success(request, "Sent to Payroll for approval. It takes effect on its start date once approved.")
            return redirect('hr:manage_salaries')
        except SalaryError as e:
            messages.error(request, str(e))
    return render(request, 'hr/manage/salary_capture.html', {'emp': emp, 'cur': cur, 'types': SalaryRecord.PAY_TYPES, 'freqs': SalaryRecord.FREQUENCY, 'active': 'pay'})


@HR_PAY
def salary_import(request):
    report = []
    if request.method == 'POST' and request.FILES.get('file'):
        try:
            report = S.import_csv(current_company(request), request.FILES['file'].read().decode('utf-8-sig'), request.user, apply=request.POST.get('apply') == '1')
            if request.POST.get('apply') == '1' and not [r for r in report if r['status'] == 'rejected']:
                messages.success(request, "Salaries loaded.")
                return redirect('hr:manage_salaries')
        except SalaryError as e:
            messages.error(request, str(e))
    return render(request, 'hr/manage/salary_import.html', {'report': report, 'active': 'pay'})


# ================================================================== payrun runs
@PAYROLL_ONLY
def runs(request):
    company = current_company(request)
    periods = PayPeriod.objects.filter(company=company)
    if request.method == 'POST':
        period = get_object_or_404(PayPeriod, pk=request.POST.get('period'), company=company)
        run = P.get_run(period, request.user)
        return redirect('hr:manage_run', run.pk)
    return render(request, 'hr/manage/runs.html', {'runs': PayrunRun.objects.filter(pay_period__company=company).select_related('pay_period'), 'periods': periods, 'active': 'pay'})


@PAYROLL_ONLY
def run_detail(request, pk):
    run = get_object_or_404(PayrunRun.objects.select_related('pay_period'), pk=pk, pay_period__company=current_company(request))
    if request.method == 'POST':
        act = request.POST.get('action')
        try:
            if act == 'import' and request.FILES.get('file'):
                n, problems = P.import_lines(run, request.FILES['file'].read().decode('utf-8-sig'), request.user)
                messages.success(request, f"{n} line(s) loaded." + (f" {len(problems)} problem(s): " + "; ".join(problems[:4]) if problems else ""))
            elif act == 'lock':
                total, result = P.lock(run, request.user)
                messages.success(request, f"Locked. Advance recoveries taken: R{total}. Sync: {result}")
        except PayrunError as e:
            messages.error(request, str(e))
        return redirect('hr:manage_run', run.pk)
    return render(request, 'hr/manage/run_detail.html', {'run': run, 'lines': run.lines.select_related('employee'),
                                                         'preview': P.preview_recoveries(run) if run.status == 'OPEN' else [], 'active': 'pay'})


# ================================================================== sync console
@PAYROLL_ONLY
def sync_console(request):
    company = current_company(request)
    ps = S.get_pay_settings(company)
    if request.method == 'POST':
        act = request.POST.get('action')
        try:
            if act == 'settings':
                for f in ('salary_sync_enabled', 'post_advances_to_reconciliation', 'allow_role_overlap'):
                    setattr(ps, f, bool(request.POST.get(f)))
                ps.sync_amount_basis = request.POST.get('sync_amount_basis', ps.sync_amount_basis)
                ps.books_closed_through = _date(request.POST.get('books_closed_through'))
                ps.save()
                audit.log('sync.settings', 'sync', request=request, obj=ps, new={'enabled': ps.salary_sync_enabled})
                messages.success(request, "Saved.")
            elif act == 'link':
                Y.link_manually(get_object_or_404(Employee, pk=request.POST.get('employee'), company=company), request.POST.get('ref', '').strip(), request.user)
            elif act == 'nocounterpart':
                Y.mark_no_counterpart(get_object_or_404(Employee, pk=request.POST.get('employee'), company=company), request.user)
                messages.success(request, "Recorded: this person has no reconciliation counterpart.")
            elif act == 'run':
                n = Y.sync_due_salaries() + Y.retry_failed(request.user)
                messages.success(request, f"Sync run complete ({n} item(s)).")
            elif act in ('approve', 'decline'):
                adj = get_object_or_404(AdjustmentEntry, pk=request.POST.get('adj'), employee__company=company)
                Y.resolve_adjustment(adj, request.user, act == 'approve')
        except (ValueError, Exception) as e:  # noqa
            messages.error(request, str(e))
        return redirect('hr:manage_sync')
    return render(request, 'hr/manage/sync.html', {
        'ps': ps, 'unmatched': Y.unmatched(company), 'log': SyncLog.objects.all()[:60],
        'adjustments': AdjustmentEntry.objects.filter(employee__company=company, status='PENDING'),
        'diffs': Y.daily_comparison(company), 'first_load': Y.first_load_report(company), 'active': 'pay'})


# ================================================================== reports
@HR_PAY
def pay_reports(request, kind='outstanding'):
    company = current_company(request)
    end = _date(request.GET.get('end')) or timezone.localdate()
    start = _date(request.GET.get('start')) or end - timedelta(days=89)
    title, cols, rows = '', [], []
    if kind == 'monthly':
        title, cols = "Advances by person and month", ['Employee', 'Month', 'Advances', 'Total (R)']
        rows = [[r['employee'], r['month'], r['count'], f"{r['total']:,.2f}"] for r in A.report_by_person_month(company, start, end)]
    elif kind == 'outstanding':
        title, cols = "Outstanding advances", ['Employee', 'Advance', 'Balance (R)', 'Age (days)', 'Status']
        rows = [[r['advance'].employee, r['advance'].number, f"{r['balance']:,.2f}", r['age_days'], r['advance'].get_status_display()] for r in A.report_outstanding(company)]
    elif kind == 'schedule':
        title, cols = "Recovery schedule", ['Employee', 'Advance', 'Instalment', 'Amount (R)']
        rows = [[s.advance.employee, s.advance.number, s.sequence, f"{s.amount:,.2f}"] for s in A.report_schedule(company)]
    elif kind == 'source':
        title, cols = "Advances paid by till and petty cash", ['Source', 'Advances', 'Total (R)']
        rows = [[r['source'], r['count'], f"{r['total']:,.2f}"] for r in A.report_by_source(company, start, end)]
    elif kind == 'exceptions':
        title, cols = "Policy exceptions (emergency advances)", ['Advance', 'Employee', 'Amount (R)', 'Reason', 'Captured by', 'Approved by']
        rows = [[a.number, a.employee, f"{a.amount:,.2f}", a.emergency_reason, a.captured_by or '', a.approved_by or ''] for a in A.report_exceptions(company)]
    elif kind == 'leavers':
        title, cols = "Leavers with a balance", ['Employee', 'Advance', 'Balance (R)', 'Final pay agreed']
        rows = [[r['advance'].employee, r['advance'].number, f"{r['balance']:,.2f}", 'Yes' if r['agreed'] else 'No'] for r in A.leaver_balances(company)]
    elif kind == 'salary':
        title, cols = "Salary changes", ['Employee', 'Type', 'From', 'Status', 'Captured by', 'Approved by', 'Sync']
        rows = [[r.employee, r.get_pay_type_display(), r.start_date, r.get_status_display(), r.captured_by or '', r.approved_by or '', r.get_sync_status_display()]
                for r in S.salary_report(company, start, end)]
        audit.log('salary.report', 'salary', request=request, sensitive=True, description='Salary changes report')
    else:
        from django.http import Http404
        raise Http404
    if request.GET.get('csv'):
        audit.log('report.export', 'pay', request=request, sensitive=True, description=f'Pay report {kind}')
        resp = HttpResponse(content_type='text/csv')
        resp['Content-Disposition'] = f'attachment; filename="{kind}.csv"'
        w = csv.writer(resp)
        w.writerow(cols)
        for r in rows:
            w.writerow([str(c) for c in r])
        return resp
    kinds = [('outstanding', 'Outstanding advances'), ('monthly', 'By person and month'), ('schedule', 'Recovery schedule'), ('source', 'By till and petty cash'),
             ('exceptions', 'Policy exceptions'), ('leavers', 'Leavers with a balance'), ('salary', 'Salary changes')]
    return render(request, 'hr/manage/pay_reports.html', {'kind': kind, 'kinds': kinds, 'title': title, 'cols': cols, 'rows': rows, 'start': start, 'end': end, 'active': 'pay'})

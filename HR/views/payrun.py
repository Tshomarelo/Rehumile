import csv
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import PayPeriod, PayrunInput, WorkflowInstance, PAYROLL_ADMIN, SUPER_ADMIN
from ..services import audit, files, workflow
from ..services.access import current_company, employee_for, portal_required, role_required
from ..services.workflow import WorkflowError

PAYROLL = role_required(PAYROLL_ADMIN, SUPER_ADMIN)


def open_periods(company):
    """Periods still accepting input: cut-off today or later (or none set) and not yet over long ago."""
    today = timezone.localdate()
    return [p for p in PayPeriod.objects.filter(company=company, end_date__gte=today.replace(day=1).replace(year=today.year - 1))
            if (p.input_cutoff is None and p.end_date >= today.replace(day=1)) or (p.input_cutoff and p.input_cutoff >= today)]


def _dec(v):
    v = (v or '').strip()
    try:
        return Decimal(v.replace(',', '')) if v else None
    except InvalidOperation:
        raise WorkflowError("Enter numbers only for hours and amount.")


@portal_required
def payrun_input(request):
    emp = employee_for(request.user)
    periods = open_periods(emp.company)
    if request.method == 'POST':
        try:
            period = next((p for p in periods if str(p.pk) == request.POST.get('period')), None)
            if period is None:
                raise WorkflowError("That pay period is closed for input. Ask Payroll if it is urgent.")
            kind = request.POST.get('kind')
            if kind not in dict(PayrunInput.KIND_CHOICES):
                raise WorkflowError("Choose what you are claiming.")
            desc = request.POST.get('description', '').strip()
            hours, amount = _dec(request.POST.get('hours')), _dec(request.POST.get('amount'))
            if not desc:
                raise WorkflowError("Describe the claim.")
            if kind == 'OVERTIME' and not hours:
                raise WorkflowError("Enter the overtime hours.")
            if kind != 'OVERTIME' and not amount:
                raise WorkflowError("Enter the amount.")
            if kind == 'EXPENSE' and not request.FILES.get('receipt'):
                raise WorkflowError("Attach the receipt for an expense claim.")
            with transaction.atomic():
                r = PayrunInput.objects.create(
                    employee=emp, pay_period=period, kind=kind, description=desc[:200],
                    work_date=request.POST.get('work_date') or None, hours=hours, amount=amount,
                    receipt=request.FILES.get('receipt'))
                workflow.start(r, 'payrun_input', request.user, emp, f"{r.get_kind_display()} for {period.label}: {emp.display_name}")
            audit.log('payrun.submit', 'payroll', request=request, obj=r, employee=emp)
            messages.success(request, "Submitted. Your manager and then Payroll will approve it.")
            return redirect('hr:payrun_input')
        except WorkflowError as e:
            messages.error(request, str(e))
    rows = list(emp.payrun_inputs.select_related('pay_period')[:40])
    for r in rows:
        r.receipt_url = files.make_url(request.user, 'receipt', r) if r.receipt else ''
    return render(request, 'hr/payrun_input.html', {
        'periods': periods, 'kinds': PayrunInput.KIND_CHOICES, 'rows': rows, 'active': 'payrun-input'})


@portal_required
@require_POST
def payrun_withdraw(request, pk):
    emp = employee_for(request.user)
    r = get_object_or_404(PayrunInput, pk=pk, employee=emp, status='PENDING')
    inst = WorkflowInstance.objects.filter(content_type=ContentType.objects.get_for_model(r), object_id=r.pk, status='PENDING').first()
    if inst:
        workflow.withdraw(inst, request.user)
    messages.success(request, "Withdrawn.")
    return redirect('hr:payrun_input')


@PAYROLL
def payrun_admin(request):
    company = current_company(request)
    periods = PayPeriod.objects.filter(company=company)
    pid = request.GET.get('period') or (periods.first().pk if periods else None)
    rows = PayrunInput.objects.filter(pay_period_id=pid, employee__company=company).select_related('employee', 'pay_period') if pid else []
    return render(request, 'hr/manage/payrun.html', {'periods': periods, 'pid': int(pid) if pid else None, 'rows': rows, 'active': 'payroll'})


@PAYROLL
@require_POST
def payrun_cutoff(request, pk):
    p = get_object_or_404(PayPeriod, pk=pk, company=current_company(request))
    from datetime import date
    try:
        p.input_cutoff = date.fromisoformat(request.POST.get('cutoff') or '')
    except ValueError:
        p.input_cutoff = None
    p.save(update_fields=['input_cutoff'])
    messages.success(request, "Cut-off saved.")
    from django.urls import reverse
    return redirect(reverse('hr:manage_payrun') + f'?period={pk}')


@PAYROLL
def payrun_export(request, pk):
    p = get_object_or_404(PayPeriod, pk=pk, company=current_company(request))
    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = f'attachment; filename="payrun-input-{p.label}.csv"'
    w = csv.writer(resp)
    w.writerow(['employee_number', 'name', 'type', 'description', 'date', 'hours', 'amount'])
    for r in PayrunInput.objects.filter(pay_period=p, status='APPROVED').select_related('employee'):
        w.writerow([r.employee.employee_number, r.employee.display_name, r.get_kind_display(), r.description,
                    r.work_date or '', r.hours or '', r.amount or ''])
    audit.log('payrun.export', 'payroll', request=request, obj=p, sensitive=True)
    return resp

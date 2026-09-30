from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import BatchForm, ChangeForm
from ..models import (ChangeRequest, Employee, ImportBatch, PayPeriod, Payslip, TaxCertificate, TaxYear,
                      WorkflowInstance, PAYROLL_ADMIN, SUPER_ADMIN)
from ..services import audit, biographical as B, files, payroll, workflow
from ..services import payrun as payrun_service
from ..services.access import current_company, employee_for, portal_required, role_required
from ..services.notify import notify
from ..services.workflow import WorkflowError

VISIBLE = ('PUBLISHED', 'CORRECTION')


# ------------------------------------------------------------ biographical
@portal_required
def biographical(request):
    emp = employee_for(request.user)
    return render(request, 'hr/biographical.html', {
        'emp': emp, 'active': 'biographical',
        'pending': emp.change_requests.filter(status='PENDING'),
        'address': getattr(emp, 'address', None), 'bank': getattr(emp, 'bank_account', None),
        'emergency': emp.emergency_contacts.all(), 'dependants': emp.dependants.all(),
        'qualifications': emp.qualifications.all(), 'history': emp.change_requests.all()[:15],
    })


@portal_required
def change_edit(request, section, pk=None):
    emp = employee_for(request.user)
    if section not in B.SECTIONS:
        return redirect('hr:biographical')
    label, model, fields, is_list, proof_needed, key = B.SECTIONS[section]
    action = 'UPDATE' if (pk or not is_list) else 'ADD'
    form = ChangeForm(section, request.POST or None, request.FILES or None, initial=B.current_values(emp, section, pk))
    if request.method == 'POST' and form.is_valid():
        vals = {f: form.cleaned_data.get(f) for f in fields}
        try:
            B.submit(emp, request.user, section, action, vals, pk, form.cleaned_data.get('proof'))
            messages.success(request, "Sent for approval. Your details change once it is approved.")
            return redirect('hr:biographical')
        except WorkflowError as e:
            messages.error(request, str(e))
    return render(request, 'hr/change_form.html', {'form': form, 'label': label, 'active': 'biographical',
                                                  'bank': section == 'bank', 'proof_needed': proof_needed})


@portal_required
@require_POST
def change_remove(request, section, pk):
    emp = employee_for(request.user)
    try:
        B.submit(emp, request.user, section, 'REMOVE', B.current_values(emp, section, pk), pk)
        messages.success(request, "Removal sent for approval.")
    except WorkflowError as e:
        messages.error(request, str(e))
    return redirect('hr:biographical')


@portal_required
@require_POST
def change_withdraw(request, pk):
    emp = employee_for(request.user)
    cr = get_object_or_404(ChangeRequest, pk=pk, employee=emp, status='PENDING')
    inst = WorkflowInstance.objects.filter(content_type=ContentType.objects.get_for_model(cr),
                                           object_id=cr.pk, status='PENDING').first()
    if inst:
        workflow.withdraw(inst, request.user)
    messages.success(request, "Change withdrawn.")
    return redirect('hr:biographical')


# --------------------------------------------------------- payslips / tax
@portal_required
def payslips(request):
    emp = employee_for(request.user)
    rows = list(Payslip.objects.filter(employee=emp, status='PUBLISHED').select_related('pay_period'))
    years = {}
    for r in rows:
        r.open_url = files.make_url(request.user, 'payslip', r)
        r.dl_url = files.make_url(request.user, 'payslip', r, download=True)
        r.adv = payrun_service.payslip_advance_info(emp, r.pay_period)
        years.setdefault(r.pay_period.tax_year, []).append(r)
    ytd = None
    if years:
        latest = max(years)
        got = [r for r in years[latest] if r.gross is not None]
        if got:
            ytd = {'year': latest, 'gross': sum(r.gross for r in got),
                   'deductions': sum((r.deductions or 0) for r in got), 'net': sum((r.net or 0) for r in got)}
    return render(request, 'hr/payslips.html', {'years': sorted(years.items(), reverse=True), 'ytd': ytd, 'active': 'payslips'})


@portal_required
def tax_certificates(request):
    emp = employee_for(request.user)
    rows = list(TaxCertificate.objects.filter(employee=emp, status__in=VISIBLE).select_related('tax_year'))
    for r in rows:
        r.open_url = files.make_url(request.user, 'taxcert', r)
        r.dl_url = files.make_url(request.user, 'taxcert', r, download=True)
    return render(request, 'hr/tax_certificates.html', {'rows': rows, 'active': 'tax-certificate'})


@portal_required
@require_POST
def tax_correction(request, pk):
    emp = employee_for(request.user)
    c = get_object_or_404(TaxCertificate, pk=pk, employee=emp, status='PUBLISHED')
    note = request.POST.get('note', '').strip()
    if not note:
        messages.error(request, "Say what is wrong so Payroll can correct it.")
    else:
        c.status, c.correction_note, c.correction_requested_at = 'CORRECTION', note, timezone.now()
        c.save(update_fields=['status', 'correction_note', 'correction_requested_at'])
        audit.log('taxcert.correction', 'payroll', request=request, obj=c, employee=emp, new={'note': note})
        notify(list(workflow._role_holders(PAYROLL_ADMIN)), 'payroll', f"Tax certificate correction: {emp.display_name}", note)
        messages.success(request, "Payroll has been told. A reissued certificate will replace this one.")
    return redirect('hr:tax_certificates')


@login_required
def file_open(request, token):
    return files.open_file(request, token)


# ------------------------------------------------------ payroll admin site
PAYROLL = role_required(PAYROLL_ADMIN, SUPER_ADMIN)


@PAYROLL
def batches(request):
    company = current_company(request)
    return render(request, 'hr/manage/batches.html', {
        'batches': ImportBatch.objects.filter(company=company)[:50], 'active': 'payroll',
        'corrections': TaxCertificate.objects.filter(employee__company=company, status='CORRECTION').select_related('employee', 'tax_year'),
    })


@PAYROLL
def batch_new(request, kind):
    company = current_company(request)
    kind = 'PAYSLIP' if kind == 'payslips' else 'TAXCERT'
    form = BatchForm(request.POST or None, request.FILES or None)
    extra = {'periods': PayPeriod.objects.filter(company=company)} if kind == 'PAYSLIP' else {'years': TaxYear.objects.filter(company=company)}
    if request.method == 'POST' and form.is_valid():
        b = ImportBatch(company=company, kind=kind, uploaded_by=request.user, source_file=form.cleaned_data['source_file'],
                        data_file=form.cleaned_data.get('data_file'), publish_at=form.cleaned_data.get('publish_at'))
        if kind == 'PAYSLIP':
            b.pay_period = get_object_or_404(PayPeriod, pk=request.POST.get('period'), company=company)
        else:
            b.tax_year = get_object_or_404(TaxYear, pk=request.POST.get('year'), company=company)
            b.cert_type = request.POST.get('cert_type', 'IRP5')
        b.save()
        try:
            payroll.build_preview(b)
        except Exception as e:
            b.status = 'CANCELLED'
            b.summary = f"Could not read the file: {e}"[:255]
            b.save()
            messages.error(request, b.summary)
            return redirect('hr:manage_batches')
        audit.log('batch.upload', 'payroll', request=request, obj=b, new={'summary': b.summary}, sensitive=True)
        return redirect('hr:manage_batch', b.pk)
    return render(request, 'hr/manage/batch_form.html', {'form': form, 'kind': kind, 'active': 'payroll', **extra})


@PAYROLL
def batch_detail(request, pk):
    b = get_object_or_404(ImportBatch, pk=pk, company=current_company(request))
    rows = (b.payslips if b.kind == 'PAYSLIP' else b.certificates).select_related('employee')
    return render(request, 'hr/manage/batch_detail.html', {
        'b': b, 'rows': rows, 'active': 'payroll',
        'people': Employee.objects.filter(company=b.company).order_by('surname'),
    })


@PAYROLL
@require_POST
def batch_action(request, pk):
    b = get_object_or_404(ImportBatch, pk=pk, company=current_company(request))
    act = request.POST.get('action')
    if b.status not in ('PREVIEW', 'SCHEDULED'):
        messages.error(request, "This batch is already closed.")
    elif act == 'publish':
        n = payroll.publish(b, request.user)
        messages.success(request, f"Published {n} document(s). Employees have been notified.")
    elif act == 'schedule' and b.publish_at:
        b.status = 'SCHEDULED'
        b.save(update_fields=['status'])
        messages.success(request, f"Scheduled for {b.publish_at:%d %b %Y %H:%M}.")
    elif act == 'cancel':
        b.status = 'CANCELLED'
        b.save(update_fields=['status'])
        (b.payslips if b.kind == 'PAYSLIP' else b.certificates).filter(status='DRAFT').delete()
        messages.success(request, "Batch cancelled and drafts removed.")
    return redirect('hr:manage_batch', b.pk)


@PAYROLL
@require_POST
def row_assign(request, kind, pk):
    model = Payslip if kind == 'payslip' else TaxCertificate
    r = get_object_or_404(model, pk=pk, status='DRAFT')
    r.employee = get_object_or_404(Employee, pk=request.POST.get('employee'))
    r.match_note = 'Assigned by hand'
    r.save(update_fields=['employee', 'match_note'])
    return redirect('hr:manage_batch', r.batch_id)


@PAYROLL
@require_POST
def row_withdraw(request, kind, pk):
    model = Payslip if kind == 'payslip' else TaxCertificate
    r = get_object_or_404(model, pk=pk)
    r.status = 'WITHDRAWN'
    r.save(update_fields=['status'])
    audit.log('payroll.withdraw', 'payroll', request=request, obj=r, employee=r.employee, sensitive=True)
    messages.success(request, "Withdrawn. The employee can no longer see it.")
    return redirect('hr:manage_batches')


@PAYROLL
def periods(request):
    from datetime import date
    company = current_company(request)
    if request.method == 'POST':
        try:
            s = date.fromisoformat(request.POST['start'])
            e = date.fromisoformat(request.POST['end'])
            PayPeriod.objects.create(company=company, label=request.POST['label'].strip(), start_date=s, end_date=e,
                                     tax_year=PayPeriod.tax_year_for(e))
            TaxYear.objects.get_or_create(company=company, year=PayPeriod.tax_year_for(e))
            messages.success(request, "Pay period added.")
        except Exception as ex:
            messages.error(request, f"Could not add: {ex}")
        return redirect('hr:manage_periods')
    return render(request, 'hr/manage/periods.html', {'periods': PayPeriod.objects.filter(company=company), 'active': 'payroll'})

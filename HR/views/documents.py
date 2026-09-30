from datetime import date

from django.contrib import messages
from django.core.files.base import File
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import (DocumentRequest, Employee, EmployeeDocument, Policy, PolicyAcknowledgement, PolicyVersion,
                      HR_ADMIN, SUPER_ADMIN)
from ..services import audit, files, workflow
from ..services.access import current_company, employee_for, portal_required, role_required
from ..services.notify import notify
from ..services.workflow import WorkflowError

HR = role_required(HR_ADMIN, SUPER_ADMIN)


def _ip(request):
    return request.META.get('REMOTE_ADDR') or None


# ------------------------------------------------------------- employee
@portal_required
def documents(request):
    emp = employee_for(request.user)
    docs = list(emp.documents.filter(status='ACTIVE'))
    for d in docs:
        d.open_url = files.make_url(request.user, 'doc', d)
        d.dl_url = files.make_url(request.user, 'doc', d, download=True)
    acked = set(PolicyAcknowledgement.objects.filter(employee=emp).values_list('version_id', flat=True))
    policies = []
    for p in Policy.objects.filter(company=emp.company, is_active=True):
        v = p.current
        if v:
            policies.append({'p': p, 'v': v, 'acked': v.pk in acked, 'url': files.make_url(request.user, 'policy', v)})
    return render(request, 'hr/documents.html', {
        'docs': docs, 'policies': policies, 'requests': emp.document_requests.all()[:20],
        'types': DocumentRequest.TYPE_CHOICES, 'active': 'documents',
        'to_sign': sum(1 for d in docs if d.requires_signature and not d.signed_at),
        'to_ack': sum(1 for x in policies if x['v'].requires_ack and not x['acked']),
    })


@portal_required
@require_POST
def doc_sign(request, pk):
    emp = employee_for(request.user)
    d = get_object_or_404(EmployeeDocument, pk=pk, employee=emp, status='ACTIVE', requires_signature=True)
    name = request.POST.get('name', '').strip()
    expected = f"{emp.first_names} {emp.surname}".lower().split()
    if d.signed_at:
        messages.info(request, "Already signed.")
    elif not name or [w.lower() for w in name.split()] != expected and name.lower() != emp.display_name.lower():
        messages.error(request, "Type your full name exactly as shown to sign.")
    else:
        d.signed_at, d.signed_name, d.signed_ip = timezone.now(), name, _ip(request)
        d.save(update_fields=['signed_at', 'signed_name', 'signed_ip'])
        audit.log('doc.sign', 'documents', request=request, obj=d, employee=emp, new={'name': name})
        messages.success(request, "Signed. HR has a record of the date and time.")
    return redirect('hr:documents')


@portal_required
@require_POST
def policy_ack(request, pk):
    emp = employee_for(request.user)
    v = get_object_or_404(PolicyVersion, pk=pk, policy__company=emp.company)
    if v.pk != v.policy.current.pk:
        messages.error(request, "A newer version has been published. Please read it.")
    else:
        PolicyAcknowledgement.objects.get_or_create(version=v, employee=emp, defaults={'ip': _ip(request)})
        audit.log('policy.ack', 'documents', request=request, obj=v, employee=emp)
        messages.success(request, "Thank you. Your acknowledgement is recorded.")
    return redirect('hr:documents')


@portal_required
@require_POST
def request_letter(request):
    emp = employee_for(request.user)
    kind = request.POST.get('doc_type')
    if kind not in dict(DocumentRequest.TYPE_CHOICES):
        messages.error(request, "Choose what you need.")
        return redirect('hr:documents')
    with transaction.atomic():
        r = DocumentRequest.objects.create(employee=emp, doc_type=kind, note=request.POST.get('note', '')[:255])
        workflow.start(r, 'document_request', request.user, emp, f"{r.get_doc_type_display()} for {emp.display_name}")
    messages.success(request, "Request sent to HR.")
    return redirect('hr:documents')


# ------------------------------------------------------------- admin site
@HR
def manage_documents(request):
    company = current_company(request)
    return render(request, 'hr/manage/documents.html', {
        'requests': DocumentRequest.objects.filter(employee__company=company).exclude(status__in=('READY', 'REJECTED', 'WITHDRAWN')).select_related('employee'),
        'docs': EmployeeDocument.objects.filter(employee__company=company).select_related('employee')[:60],
        'people': Employee.objects.filter(company=company).order_by('surname'),
        'policies': Policy.objects.filter(company=company),
        'categories': EmployeeDocument.CATEGORY_CHOICES, 'active': 'documents',
    })


@HR
@require_POST
def doc_upload(request):
    company = current_company(request)
    emp = get_object_or_404(Employee, pk=request.POST.get('employee'), company=company)
    f = request.FILES.get('file')
    if not f or not request.POST.get('title', '').strip():
        messages.error(request, "Choose an employee, a title and a file.")
        return redirect('hr:manage_documents')
    d = EmployeeDocument.objects.create(
        employee=emp, title=request.POST['title'].strip(), category=request.POST.get('category', 'OTHER'), file=f,
        requires_signature=bool(request.POST.get('requires_signature')), uploaded_by=request.user)
    audit.log('doc.upload', 'documents', request=request, obj=d, employee=emp, sensitive=True)
    if emp.user:
        notify([emp.user], 'documents', f"New document: {d.title}",
               "Please open it and sign." if d.requires_signature else "It is in your Documents.", reverse('hr:documents'))
    messages.success(request, "Document filed.")
    return redirect('hr:manage_documents')


@HR
@require_POST
def doc_withdraw(request, pk):
    d = get_object_or_404(EmployeeDocument, pk=pk)
    d.status = 'WITHDRAWN'
    d.save(update_fields=['status'])
    audit.log('doc.withdraw', 'documents', request=request, obj=d, employee=d.employee)
    return redirect('hr:manage_documents')


@HR
@require_POST
def request_fulfil(request, pk):
    r = get_object_or_404(DocumentRequest, pk=pk, status='APPROVED')
    f = request.FILES.get('file')
    if not f:
        messages.error(request, "Attach the letter.")
        return redirect('hr:manage_documents')
    d = EmployeeDocument.objects.create(employee=r.employee, title=r.get_doc_type_display(), category='CERT',
                                        file=f, uploaded_by=request.user)
    r.document, r.status = d, 'READY'
    r.save(update_fields=['document', 'status'])
    audit.log('docrequest.fulfil', 'documents', request=request, obj=r, employee=r.employee, sensitive=True)
    if r.employee.user:
        notify([r.employee.user], 'documents', "Your document is ready", r.get_doc_type_display(), reverse('hr:documents'))
    messages.success(request, "Sent to the employee.")
    return redirect('hr:manage_documents')


@HR
@require_POST
def policy_publish(request):
    """Create a policy (new title) or add a new version of an existing one."""
    company = current_company(request)
    f = request.FILES.get('file')
    if not f:
        messages.error(request, "Attach the policy file.")
        return redirect('hr:manage_documents')
    pid = request.POST.get('policy')
    if pid:
        p = get_object_or_404(Policy, pk=pid, company=company)
    else:
        title = request.POST.get('title', '').strip()
        if not title:
            messages.error(request, "Give the new policy a title.")
            return redirect('hr:manage_documents')
        p = Policy.objects.create(company=company, title=title, summary=request.POST.get('summary', '')[:255])
    last = p.current
    try:
        eff = date.fromisoformat(request.POST.get('effective_date') or '')
    except ValueError:
        eff = timezone.localdate()
    v = PolicyVersion.objects.create(policy=p, version=(last.version + 1) if last else 1, file=f, effective_date=eff,
                                     requires_ack=bool(request.POST.get('requires_ack')),
                                     change_note=request.POST.get('change_note', '')[:255])
    audit.log('policy.publish', 'documents', request=request, obj=v, new={'version': v.version})
    if v.requires_ack:
        users = [e.user for e in Employee.objects.filter(company=company, status='ACTIVE').select_related('user') if e.user]
        notify(users, 'documents', f"Please read: {p.title}", "A policy needs your acknowledgement.", reverse('hr:documents'))
    messages.success(request, f"{p.title} v{v.version} published.")
    return redirect('hr:manage_documents')


@HR
def policy_acks(request, pk):
    p = get_object_or_404(Policy, pk=pk, company=current_company(request))
    v = p.current
    people = Employee.objects.filter(company=p.company, status='ACTIVE').order_by('surname')
    acked = {a.employee_id: a for a in v.acknowledgements.all()} if v else {}
    rows = [{'e': e, 'a': acked.get(e.pk)} for e in people]
    return render(request, 'hr/manage/policy_acks.html', {
        'p': p, 'v': v, 'rows': rows, 'done': sum(1 for r in rows if r['a']), 'active': 'documents'})

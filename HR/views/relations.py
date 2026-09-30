from datetime import date, datetime

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import (Employee, Grievance, GrievanceNote, Hearing, Warning, HR_ADMIN, SUPER_ADMIN)
from ..services import audit, files
from ..services.access import current_company, employee_for, portal_required, role_required
from ..services.notify import notify
from ..services.workflow import _role_holders

HR = role_required(HR_ADMIN, SUPER_ADMIN)


# ------------------------------------------------------------ employee
@portal_required
def relations(request):
    emp = employee_for(request.user)
    warns = list(emp.warnings.filter(withdrawn=False))
    for w in warns:
        w.doc_url = files.make_url(request.user, 'warning', w) if w.document else ''
    return render(request, 'hr/relations.html', {
        'grievances': emp.grievances.all(), 'warnings': warns,
        'hearings': emp.hearings.exclude(status='CANCELLED'), 'active': 'employee-relations'})


@portal_required
@require_POST
def grievance_raise(request):
    emp = employee_for(request.user)
    subject, text = request.POST.get('subject', '').strip(), request.POST.get('description', '').strip()
    if not subject or not text:
        messages.error(request, "Give a subject and describe what happened.")
        return redirect('hr:relations')
    g = Grievance.objects.create(employee=emp, subject=subject[:150], description=text)
    audit.log('grievance.raise', 'relations', request=request, obj=g, employee=emp, sensitive=True)
    notify(list(_role_holders(HR_ADMIN)), 'relations', "New grievance", f"{emp.display_name}: {g.subject}", reverse('hr:manage_grievance', args=[g.pk]))
    messages.success(request, "Your grievance has been received. HR will contact you.")
    return redirect('hr:relations')


@portal_required
@require_POST
def warning_ack(request, pk):
    emp = employee_for(request.user)
    w = get_object_or_404(Warning, pk=pk, employee=emp, withdrawn=False)
    if not w.acknowledged_at:
        w.acknowledged_at, w.ack_comment = timezone.now(), request.POST.get('comment', '')[:255]
        w.save(update_fields=['acknowledged_at', 'ack_comment'])
        audit.log('warning.ack', 'relations', request=request, obj=w, employee=emp, sensitive=True)
        messages.success(request, "Recorded. Acknowledging a warning does not mean you agree with it.")
    return redirect('hr:relations')


@portal_required
@require_POST
def warning_appeal(request, pk):
    emp = employee_for(request.user)
    w = get_object_or_404(Warning, pk=pk, employee=emp, withdrawn=False, appeal_status='NONE')
    text = request.POST.get('appeal', '').strip()
    if not text:
        messages.error(request, "Explain the grounds for your appeal.")
    else:
        w.appeal_status, w.appeal_text = 'PENDING', text
        w.save(update_fields=['appeal_status', 'appeal_text'])
        audit.log('warning.appeal', 'relations', request=request, obj=w, employee=emp, sensitive=True)
        notify(list(_role_holders(HR_ADMIN)), 'relations', "Warning appeal lodged", emp.display_name, reverse('hr:manage_relations'))
        messages.success(request, "Your appeal has been lodged.")
    return redirect('hr:relations')


@portal_required
@require_POST
def hearing_ack(request, pk):
    emp = employee_for(request.user)
    h = get_object_or_404(Hearing, pk=pk, employee=emp, status='INVITED')
    h.status, h.acknowledged_at = 'ACKNOWLEDGED', timezone.now()
    h.save(update_fields=['status', 'acknowledged_at'])
    audit.log('hearing.ack', 'relations', request=request, obj=h, employee=emp, sensitive=True)
    messages.success(request, "Invitation acknowledged.")
    return redirect('hr:relations')


# ------------------------------------------------------------ HR
@HR
def manage_relations(request):
    company = current_company(request)
    return render(request, 'hr/manage/relations.html', {
        'grievances': Grievance.objects.filter(employee__company=company).select_related('employee'),
        'warnings': Warning.objects.filter(employee__company=company).select_related('employee')[:50],
        'hearings': Hearing.objects.filter(employee__company=company, status__in=('INVITED', 'ACKNOWLEDGED')).select_related('employee'),
        'people': Employee.objects.filter(company=company).order_by('surname'),
        'levels': Warning.LEVEL_CHOICES, 'active': 'relations'})


@HR
def manage_grievance(request, pk):
    g = get_object_or_404(Grievance, pk=pk, employee__company=current_company(request))
    audit.log('grievance.view', 'relations', request=request, obj=g, employee=g.employee, sensitive=True)
    return render(request, 'hr/manage/grievance.html', {'g': g, 'statuses': Grievance.STATUS_CHOICES, 'active': 'relations'})


@HR
@require_POST
def grievance_update(request, pk):
    g = get_object_or_404(Grievance, pk=pk, employee__company=current_company(request))
    note = request.POST.get('note', '').strip()
    if note:
        GrievanceNote.objects.create(grievance=g, author=request.user, text=note)
    status = request.POST.get('status')
    if status in dict(Grievance.STATUS_CHOICES):
        g.status = status
    g.outcome = request.POST.get('outcome', g.outcome)
    g.save()
    audit.log('grievance.update', 'relations', request=request, obj=g, employee=g.employee, new={'status': g.status}, sensitive=True)
    if g.employee.user:
        notify([g.employee.user], 'relations', "Update on your grievance", g.get_status_display(), reverse('hr:relations'))
    messages.success(request, "Saved.")
    return redirect('hr:manage_grievance', g.pk)


@HR
@require_POST
def warning_issue(request):
    emp = get_object_or_404(Employee, pk=request.POST.get('employee'), company=current_company(request))
    try:
        issued = date.fromisoformat(request.POST.get('issued_on') or '')
        expiry = date.fromisoformat(request.POST['expiry_date']) if request.POST.get('expiry_date') else None
    except ValueError:
        messages.error(request, "Check the dates.")
        return redirect('hr:manage_relations')
    reason = request.POST.get('reason', '').strip()
    if request.POST.get('level') not in dict(Warning.LEVEL_CHOICES) or not reason:
        messages.error(request, "Choose a level and give the reason.")
        return redirect('hr:manage_relations')
    w = Warning.objects.create(employee=emp, level=request.POST['level'], reason=reason, issued_on=issued, expiry_date=expiry,
                               document=request.FILES.get('document'), issued_by=request.user)
    audit.log('warning.issue', 'relations', request=request, obj=w, employee=emp, sensitive=True)
    if emp.user:
        notify([emp.user], 'relations', f"You have received a {w.get_level_display().lower()}", "Please open it and acknowledge.", reverse('hr:relations'))
    messages.success(request, "Warning issued and the employee notified.")
    return redirect('hr:manage_relations')


@HR
@require_POST
def warning_decide(request, pk):
    w = get_object_or_404(Warning, pk=pk, employee__company=current_company(request))
    action = request.POST.get('action')
    if action == 'withdraw':
        w.withdrawn = True
    elif action in ('UPHELD', 'OVERTURNED') and w.appeal_status == 'PENDING':
        w.appeal_status, w.appeal_decision = action, request.POST.get('decision', '')
    w.save()
    audit.log('warning.decide', 'relations', request=request, obj=w, employee=w.employee, new={'action': action}, sensitive=True)
    if w.employee.user:
        notify([w.employee.user], 'relations', "Update on your warning", "Please open Employee Relations.", reverse('hr:relations'))
    return redirect('hr:manage_relations')


@HR
@require_POST
def hearing_invite(request):
    emp = get_object_or_404(Employee, pk=request.POST.get('employee'), company=current_company(request))
    try:
        when = datetime.strptime(request.POST.get('when', ''), '%Y-%m-%dT%H:%M')
    except ValueError:
        messages.error(request, "Give the date and time of the hearing.")
        return redirect('hr:manage_relations')
    h = Hearing.objects.create(employee=emp, when=timezone.make_aware(when), venue=request.POST.get('venue', '')[:150],
                               purpose=request.POST.get('purpose', 'Disciplinary hearing')[:200],
                               notes_for_employee=request.POST.get('notes', ''))
    audit.log('hearing.invite', 'relations', request=request, obj=h, employee=emp, sensitive=True)
    if emp.user:
        notify([emp.user], 'relations', "Hearing invitation", f"{h.purpose} on {h.when:%d %b %H:%M}", reverse('hr:relations'))
    messages.success(request, "Invitation sent.")
    return redirect('hr:manage_relations')

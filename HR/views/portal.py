from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import DelegationForm, PhotoForm
from ..models import Delegation, Notification
from ..services import audit
from ..services.access import employee_for, portal_required

# Modules in the employee menu that are specified but not built yet. The menu
# shows them so the shape matches the requirements; the page says what is coming.
COMING_SOON = {
    'payslips': ('Payslips', "Payslips listed by month and tax year, opened in the app or downloaded as PDF, with a year-to-date summary. Only published payslips are visible.", 'Phase 1'),
    'biographical': ('Biographical Details', "View your contact, address, emergency contact, banking and qualification details and request changes. An edit creates a change request with proof and applies once approved.", 'Phase 1'),
    'payrun-input': ('Payrun Input', "Submit overtime, allowances, expense claims and deduction requests for the coming payrun, with the cut-off date shown.", 'Phase 2'),
    'tax-certificate': ('Tax Certificate', "Certificates by tax year, viewable and downloadable as PDF, with a correction request.", 'Phase 1'),
    'documents': ('Documents', "Your contract and personal documents, the company policy library with acknowledgement, document requests and e-signing.", 'Phase 1'),
    'employee-relations': ('Employee Relations', "Raise a grievance, see warnings and hearing invitations, acknowledge or appeal.", 'Phase 2'),
    'roster': ('My Roster', "Your shifts, availability, swap and shift-change requests, and a calendar feed for your phone.", 'Phase 2'),
}


@portal_required
def home(request):
    """'This is me': photo, name, job title, employer banner and personal details."""
    emp = employee_for(request.user)
    reveal_until = request.session.get('hr_reveal_until')
    revealed = bool(reveal_until and reveal_until > timezone.now().timestamp())
    return render(request, 'hr/portal_home.html', {
        'emp': emp, 'revealed': revealed, 'photo_form': PhotoForm(instance=emp), 'active': 'home',
    })


@portal_required
@require_POST
def upload_photo(request):
    emp = employee_for(request.user)
    form = PhotoForm(request.POST, request.FILES, instance=emp)
    if form.is_valid():
        form.save()
        audit.log('profile.photo', 'profile', request=request, obj=emp)
        messages.success(request, "Your photo was updated.")
    else:
        messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect('hr:portal_home')


@portal_required
@require_POST
def reveal_sensitive(request):
    """ID number and bank details stay masked until the person re-enters their
    password. The reveal lasts five minutes and is written to the audit log."""
    user = authenticate(request, username=request.user.get_username(), password=request.POST.get('password', ''))
    emp = employee_for(request.user)
    if user is None:
        audit.log('profile.reveal_failed', 'profile', request=request, obj=emp, sensitive=True)
        messages.error(request, "That password is not correct.")
    else:
        request.session['hr_reveal_until'] = (timezone.now() + timedelta(minutes=5)).timestamp()
        audit.log('profile.reveal', 'profile', request=request, obj=emp, sensitive=True, description="Revealed own ID number")
        messages.success(request, "Sensitive details are shown for 5 minutes.")
    return redirect('hr:portal_home')


@login_required
def notifications(request):
    items = Notification.objects.filter(user=request.user)[:100]
    return render(request, 'hr/notifications.html', {'items': items, 'active': 'notifications'})


@login_required
@require_POST
def notifications_read_all(request):
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return redirect('hr:portal_notifications')


@login_required
def notification_open(request, pk):
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    if note.read_at is None:
        note.read_at = timezone.now()
        note.save(update_fields=['read_at'])
    return redirect(note.url or 'hr:portal_notifications')


@login_required
def coming_soon(request, module):
    title, blurb, phase = COMING_SOON.get(module, (module.title(), '', ''))
    return render(request, 'hr/coming_soon.html', {'title': title, 'blurb': blurb, 'phase': phase, 'active': module})


@login_required
def delegations(request):
    """A manager hands their approvals to someone else for a date range."""
    form = DelegationForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.save(commit=False)
        d.delegator = request.user
        d.save()
        audit.log('delegation.create', 'workflow', request=request, obj=d,
                  new={'delegate': d.delegate.get_username(), 'from': d.start_date, 'to': d.end_date})
        messages.success(request, "Delegation saved.")
        return redirect('hr:portal_delegations')
    if request.method == 'POST' and request.POST.get('delete'):
        Delegation.objects.filter(pk=request.POST['delete'], delegator=request.user).delete()
        return redirect('hr:portal_delegations')
    mine = Delegation.objects.filter(delegator=request.user)
    return render(request, 'hr/delegations.html', {'form': form, 'mine': mine, 'active': 'delegations'})

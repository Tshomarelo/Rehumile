import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import LeaveApplyForm
from ..models import Employee, LeaveRequest, LeaveTransaction
from ..services import leave as L
from ..services import workflow
from ..services.access import employee_for, portal_required, team_of, can_view_employee, has_role
from ..models import ADMIN_ROLES, LINE_MANAGER
from ..services.workflow import WorkflowError


@portal_required
def leave_home(request):
    emp = employee_for(request.user)
    return render(request, 'hr/leave_home.html', {
        'emp': emp, 'balances': L.balances_for(emp),
        'requests': LeaveRequest.objects.filter(employee=emp).select_related('leave_type')[:50],
        'active': 'leave',
    })


@portal_required
def leave_apply(request):
    emp = employee_for(request.user)
    form = LeaveApplyForm(emp, request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        req, errors = L.create_request(
            emp, d['leave_type'], d['start_date'], d['end_date'], d['half_day_start'], d['half_day_end'],
            d['reason'], d.get('attachment'), request.user)
        if errors:
            for e in errors:
                form.add_error(None, e)
        else:
            messages.success(request, "Your leave request was submitted for approval.")
            return redirect('hr:leave_detail', pk=req.pk)
    return render(request, 'hr/leave_apply.html', {'form': form, 'emp': emp, 'active': 'leave'})


@portal_required
def leave_preview(request):
    """Live check while filling in the form: working days and any rule that fails."""
    emp = employee_for(request.user)
    try:
        lt = L.leave_types_for(emp).get(pk=request.GET.get('leave_type'))
        start = date.fromisoformat(request.GET.get('start_date', ''))
        end = date.fromisoformat(request.GET.get('end_date', ''))
    except Exception:
        return JsonResponse({'days': None, 'errors': []})
    days, errors = L.validate_request(
        emp, lt, start, end, request.GET.get('half_day_start') == 'true', request.GET.get('half_day_end') == 'true',
        has_attachment=request.GET.get('has_attachment') == 'true')
    bal = L.balance_summary(emp, lt)
    return JsonResponse({'days': L.fmt(days), 'errors': errors, 'available': L.fmt(bal['available'])})


@portal_required
def leave_detail(request, pk):
    req = get_object_or_404(LeaveRequest.objects.select_related('employee', 'leave_type'), pk=pk)
    if not can_view_employee(request.user, req.employee):
        return render(request, 'hr/no_employee.html', status=403)
    inst = L.latest_instance(req)
    return render(request, 'hr/leave_detail.html', {
        'req': req, 'inst': inst, 'steps': inst.steps.select_related('assigned_to', 'acted_by') if inst else [],
        'is_mine': req.employee.user_id == request.user.pk, 'active': 'leave',
    })


@portal_required
@require_POST
def leave_cancel(request, pk):
    req = get_object_or_404(LeaveRequest, pk=pk, employee__user=request.user)
    try:
        was_approved = req.status == 'APPROVED'
        L.request_cancellation(req, request.user)
        messages.success(request, "Cancellation sent to your manager." if was_approved else "Your request was withdrawn.")
    except WorkflowError as e:
        messages.error(request, str(e))
    return redirect('hr:leave_detail', pk=pk)


@portal_required
def leave_calendar(request):
    """Who is off. Managers and HR see their whole team; everyone else sees
    their team-mates. When the company hides names, other people show as
    'Unavailable'."""
    emp = employee_for(request.user)
    today = timezone.localdate()
    try:
        year, month = int(request.GET.get('year', today.year)), int(request.GET.get('month', today.month))
        first = date(year, month, 1)
    except ValueError:
        first = date(today.year, today.month, 1)
    last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])

    if has_role(request.user, LINE_MANAGER, *ADMIN_ROLES):
        people = team_of(request.user) | Employee.objects.filter(pk=emp.pk)
    else:
        peers = Employee.objects.filter(manager_id=emp.manager_id) if emp.manager_id else Employee.objects.filter(pk=emp.pk)
        people = peers | Employee.objects.filter(pk=emp.pk)
    people = people.filter(company=emp.company).distinct().order_by('surname', 'known_as')
    reqs = L.team_calendar(emp.company, first, last, visible_employees=people)

    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    show_names = emp.company.show_team_leave_names or has_role(request.user, LINE_MANAGER, *ADMIN_ROLES)
    rows = []
    for person in people:
        cells = []
        person_reqs = [r for r in reqs if r.employee_id == person.pk]
        for d in days:
            hit = next((r for r in person_reqs if r.start_date <= d <= r.end_date), None)
            cells.append(hit)
        if not any(cells) and person.pk != emp.pk:
            continue
        label = person.display_name if (show_names or person.pk == emp.pk) else "Unavailable"
        rows.append({'label': label, 'cells': [
            (c, (c.leave_type.name if (show_names or person.pk == emp.pk) else 'Unavailable') if c else '') for c in cells]})
    prev_m = (first - timedelta(days=1)).replace(day=1)
    next_m = last + timedelta(days=1)
    return render(request, 'hr/leave_calendar.html', {
        'days': days, 'rows': rows, 'month_label': first.strftime('%B %Y'),
        'prev': prev_m, 'next': next_m, 'today': today, 'active': 'leave',
    })


@portal_required
def leave_statement(request):
    """A leave statement for a year: every ledger row with a running balance."""
    emp = employee_for(request.user)
    year = int(request.GET.get('year', timezone.localdate().year))
    sections = []
    for lt in L.leave_types_for(emp):
        txns = list(LeaveTransaction.objects.filter(employee=emp, leave_type=lt, date__year=year).order_by('date', 'id'))
        opening = LeaveTransaction.objects.filter(employee=emp, leave_type=lt, date__lt=date(year, 1, 1)).aggregate(s=Sum('days'))['s'] or Decimal('0')
        running, rows = opening, []
        for t in txns:
            running += t.days
            rows.append({'t': t, 'balance': running})
        sections.append({'lt': lt, 'opening': opening, 'rows': rows, 'closing': running})
    return render(request, 'hr/leave_statement.html', {'emp': emp, 'year': year, 'sections': sections, 'active': 'leave'})

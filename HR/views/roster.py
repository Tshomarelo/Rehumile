"""Roster pages: employee side (my roster, offers, swaps, availability) and manager side
(generate, review, assign, publish, reports, set-up tools)."""
import csv
import io
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.core import signing
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import (
    Availability, Employee, EmployeeFlag, Flag, Post, Roster, RosterVersion, Shift, ShiftChangeRequest, ShiftOffer,
    ShiftTemplate, Site, SiteApproval, StaffGroup, RosterProfile, RuleOverride,
    HR_ADMIN, LINE_MANAGER, SUPER_ADMIN,
)
from ..rostering import engine as E
from ..services import audit, roster_db as R
from ..services.access import current_company, employee_for, has_role, portal_required, role_required
from ..services.roster_db import RosterError

ROSTER_MANAGER = role_required(HR_ADMIN, SUPER_ADMIN, LINE_MANAGER)
ROSTER_ADMIN = role_required(HR_ADMIN, SUPER_ADMIN)
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
FEED_SALT = 'hr.roster.feed'


def _time(v):
    try:
        return datetime.strptime(v, '%H:%M').time()
    except (TypeError, ValueError):
        return None


def _date(v):
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def visible_sites(user, company):
    """MR-8: HR and Super Admin see every site; a site manager sees only theirs."""
    qs = Site.objects.filter(company=company, is_active=True)
    if user.is_superuser or has_role(user, HR_ADMIN, SUPER_ADMIN):
        return qs
    return qs.filter(managers=user)


def _shift_or_404(request, pk):
    sh = get_object_or_404(Shift.objects.select_related('site', 'roster', 'employee', 'post', 'template'), pk=pk)
    if sh.site_id and not visible_sites(request.user, current_company(request)).filter(pk=sh.site_id).exists():
        raise Http404
    return sh


# ================================================================== employee side
@portal_required
def roster(request):
    emp = employee_for(request.user)
    today = timezone.localdate()
    shifts = list(emp.shifts.filter(status='PUBLISHED', date__gte=today, date__lte=today + timedelta(days=28)).select_related('site', 'post'))
    avail = {a.weekday: a for a in emp.availability.all()}
    feed = request.build_absolute_uri(reverse('hr:roster_feed', args=[signing.dumps(emp.pk, salt=FEED_SALT)]))
    incoming = ShiftChangeRequest.objects.filter(swap_with=emp, status='AWAITING_COLLEAGUE').select_related('employee', 'shift', 'swap_shift')
    offers = ShiftOffer.objects.filter(employee=emp, status='OFFERED', shift__date__gte=today).count()
    # colleagues' upcoming shifts at the same sites, for swaps
    my_sites = {s.site_id for s in shifts}
    swap_pool = Shift.objects.filter(status='PUBLISHED', site_id__in=my_sites, employee__isnull=False, date__gte=today,
                                     date__lte=today + timedelta(days=14)).exclude(employee=emp).select_related('employee', 'site', 'post')[:120]
    st = R.get_settings(emp.company)
    return render(request, 'hr/roster.html', {
        'shifts': shifts, 'avail': [(i, n, avail.get(i)) for i, n in enumerate(DAYS)], 'feed': feed, 'incoming': incoming,
        'offers': offers, 'requests': emp.shift_requests.select_related('shift')[:15], 'swap_pool': swap_pool,
        'kinds': ShiftChangeRequest.KIND_CHOICES, 'min_notice': st.min_notice_hours, 'active': 'roster'})


@portal_required
@require_POST
def availability_save(request):
    emp = employee_for(request.user)
    for i in range(7):
        Availability.objects.update_or_create(
            employee=emp, weekday=i,
            defaults={'available': request.POST.get(f'day{i}') == 'on', 'note': request.POST.get(f'note{i}', '')[:150],
                      'from_time': _time(request.POST.get(f'from{i}')), 'to_time': _time(request.POST.get(f'to{i}'))})
    messages.success(request, "Availability saved. The roster only considers you when you are available.")
    return redirect('hr:roster')


@portal_required
@require_POST
def shift_request(request, pk):
    emp = employee_for(request.user)
    shift = get_object_or_404(Shift, pk=pk, employee=emp)
    kind = request.POST.get('kind')
    swap = None
    if request.POST.get('swap_shift'):
        swap = Shift.objects.filter(pk=request.POST['swap_shift'], status='PUBLISHED').first()
    try:
        R.request_change(emp, shift, kind, swap_shift=swap, reason=request.POST.get('reason', ''),
                         new_start=_time(request.POST.get('new_start')), new_end=_time(request.POST.get('new_end')))
        messages.success(request, "Request sent." if kind != 'SWAP' else "Sent to your colleague, then your manager.")
    except RosterError as e:
        messages.error(request, str(e))
    return redirect('hr:roster')


@portal_required
@require_POST
def request_respond(request, pk):
    emp = employee_for(request.user)
    req = get_object_or_404(ShiftChangeRequest, pk=pk, swap_with=emp)
    try:
        R.colleague_respond(req, request.POST.get('action') == 'accept', request.user)
        messages.success(request, "Answered.")
    except RosterError as e:
        messages.error(request, str(e))
    return redirect('hr:roster')


@portal_required
@require_POST
def request_cancel(request, pk):
    emp = employee_for(request.user)
    req = get_object_or_404(ShiftChangeRequest, pk=pk, employee=emp)
    try:
        R.cancel_request(req)
        messages.success(request, "Cancelled.")
    except RosterError as e:
        messages.error(request, str(e))
    return redirect('hr:roster')


@portal_required
def offers(request):
    emp = employee_for(request.user)
    rows = ShiftOffer.objects.filter(employee=emp, status='OFFERED', shift__date__gte=timezone.localdate()) \
        .select_related('shift', 'shift__site', 'shift__post')
    prof = getattr(emp, 'roster_profile', None)
    return render(request, 'hr/roster_offers.html', {'offers': rows, 'profile': prof, 'active': 'roster'})


@portal_required
@require_POST
def offer_respond(request, pk):
    emp = employee_for(request.user)
    offer = get_object_or_404(ShiftOffer, pk=pk, employee=emp)
    try:
        R.respond_offer(offer, request.POST.get('action') == 'accept', request.user)
        messages.success(request, "Thank you." if request.POST.get('action') != 'accept' else "Accepted. You will be told when it is confirmed.")
    except RosterError as e:
        messages.error(request, str(e))
    return redirect('hr:roster_offers')


def calendar_feed(request, token):
    """Read-only iCalendar feed for the employee's phone (OP-2). The token is a signature, not a login."""
    try:
        pk = signing.loads(token.removesuffix('.ics'), salt=FEED_SALT)
    except signing.BadSignature:
        raise Http404
    emp = get_object_or_404(Employee, pk=pk)
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Rehumile HR//Roster//EN', 'X-WR-CALNAME:My roster']
    for s in emp.shifts.filter(status='PUBLISHED', date__gte=timezone.localdate() - timedelta(days=7)).select_related('site', 'post'):
        lines += ['BEGIN:VEVENT', f'UID:shift-{s.pk}@rehumile', f'DTSTAMP:{timezone.now():%Y%m%dT%H%M%SZ}',
                  f'DTSTART:{s.start_at:%Y%m%dT%H%M%S}', f'DTEND:{s.end_at:%Y%m%dT%H%M%S}',
                  f'SUMMARY:Shift{" - " + s.site.name if s.site else ""}{" - " + s.post.name if s.post else ""}', 'END:VEVENT']
    lines.append('END:VCALENDAR')
    return HttpResponse('\r\n'.join(lines), content_type='text/calendar')


# ================================================================== manager side
@ROSTER_MANAGER
def manage_roster(request):
    company = current_company(request)
    sites = visible_sites(request.user, company)
    today = timezone.localdate()
    nxt = today + timedelta(days=(7 - today.weekday()))          # next Monday
    ctx = {
        'rosters': Roster.objects.filter(company=company)[:30], 'sites': sites, 'groups': StaffGroup.objects.filter(company=company),
        'default_start': nxt, 'default_end': nxt + timedelta(days=27), 'active': 'roster',
        'expiring': R.flags_expiring(company) if has_role(request.user, HR_ADMIN, SUPER_ADMIN) else [],
        'checks': R.setup_checks(company) if has_role(request.user, HR_ADMIN, SUPER_ADMIN) else [],
        'is_admin': has_role(request.user, HR_ADMIN, SUPER_ADMIN), 'today': today,
    }
    return render(request, 'hr/manage/roster_home.html', ctx)


@ROSTER_MANAGER
@require_POST
def roster_generate(request):
    company = current_company(request)
    a, b = _date(request.POST.get('start')), _date(request.POST.get('end'))
    if not (a and b) or b < a or (b - a).days > 93:
        messages.error(request, "Give a start and an end date (up to about three months).")
        return redirect('hr:manage_roster')
    site_ids = [int(x) for x in request.POST.getlist('sites') if x.isdigit()]
    allowed = set(visible_sites(request.user, company).values_list('pk', flat=True))
    site_ids = [s for s in site_ids if s in allowed] or (list(allowed) if not has_role(request.user, HR_ADMIN, SUPER_ADMIN) else [])
    roster = R.generate_roster(company, a, b, request.user, only_sites=site_ids or None)
    messages.success(request, f"Draft generated. Quality score {roster.quality_score}; {roster.summary.get('unfilled_required', 0)} required slot(s) unfilled.")
    return redirect('hr:manage_roster_detail', roster.pk)


def _grid(roster, view, sites, group_id=None):
    days = list(E.daterange(roster.start_date, roster.end_date))
    qs = roster.shifts.exclude(status='CANCELLED').select_related('employee', 'site', 'post', 'template',
                                                                   'employee__roster_profile__staff_group')
    site_ids = set(sites.values_list('pk', flat=True))
    shifts = [s for s in qs if s.site_id in site_ids or s.site_id is None]
    data = {'days': days}
    if view == 'site':
        rows = defaultdict(lambda: defaultdict(list))
        meta = {}
        for s in shifts:
            key = (s.site.name if s.site else '', s.post.name if s.post else '', s.template.name if s.template else '',
                   s.template.start_time if s.template else s.start_time)
            rows[key][s.date].append(s)
            meta[key] = s.site
        out = []
        for key in sorted(rows, key=lambda k: (k[0], k[1], k[3])):
            cells = []
            for d in days:
                items = sorted(rows[key].get(d, []), key=lambda x: (x.employee_id is None, x.slot_index))
                req = sum(1 for x in items if x.required)
                filled = sum(1 for x in items if x.employee_id)
                cells.append({'shifts': items, 'req': req, 'filled': filled, 'below': filled < req})
            out.append({'site': key[0], 'post': key[1], 'shift': f"{key[2]} {key[3]:%H:%M}", 'cells': cells})
        data['rows'] = out
    else:
        people = defaultdict(lambda: defaultdict(list))
        emps = {}
        for s in shifts:
            if s.employee_id:
                if view == 'group' and group_id and (not s.employee.roster_profile.staff_group_id or s.employee.roster_profile.staff_group_id != int(group_id)):
                    continue
                people[s.employee_id][s.date].append(s)
                emps[s.employee_id] = s.employee
        out = []
        for eid in sorted(people, key=lambda i: (emps[i].surname, emps[i].known_as)):
            total = sum(float(x.paid_hours) for d in people[eid].values() for x in d)
            out.append({'employee': emps[eid], 'cells': [people[eid].get(d, []) for d in days], 'hours': total,
                        'days_worked': len(people[eid])})
        data['rows'] = out
    return data


@ROSTER_MANAGER
def manage_roster_detail(request, pk):
    company = current_company(request)
    roster = get_object_or_404(Roster, pk=pk, company=company)
    sites = visible_sites(request.user, company)
    view = request.GET.get('view', 'site')
    grid = _grid(roster, view, sites, request.GET.get('group'))
    emps = {e.id: e for e in Employee.objects.filter(company=company)}
    hours = []
    for r in roster.summary.get('hours', []):
        e = emps.get(r['person'])
        if e and r['required'] is not None:
            state = 'under' if r['scheduled'] < r['required'] - 4 else 'over' if r['scheduled'] > r['required'] + 4 else 'ok'
            hours.append({'employee': e, 'month': r['month'], 'scheduled': r['scheduled'], 'required': r['required'], 'state': state})
    open_n = roster.shifts.filter(employee__isnull=True, required=True).exclude(status='CANCELLED').count()
    return render(request, 'hr/manage/roster_detail.html', {
        'roster': roster, 'view': view, 'grid': grid, 'warnings': roster.warnings, 'hours': hours, 'open_n': open_n,
        'groups': StaffGroup.objects.filter(company=company), 'group_id': request.GET.get('group', ''), 'sites': sites,
        'versions': roster.versions.all()[:20], 'overrides': roster.overrides.select_related('user', 'employee')[:20],
        'is_admin': has_role(request.user, HR_ADMIN, SUPER_ADMIN), 'active': 'roster'})


@ROSTER_MANAGER
@require_POST
def roster_regenerate(request, pk):
    company = current_company(request)
    roster = get_object_or_404(Roster, pk=pk, company=company, status='DRAFT')
    site_ids = [int(x) for x in request.POST.getlist('sites') if x.isdigit()]
    allowed = set(visible_sites(request.user, company).values_list('pk', flat=True))
    site_ids = [s for s in site_ids if s in allowed]
    group = request.POST.get('group')
    names = [StaffGroup.objects.get(pk=group).name] if group and group.isdigit() else None
    R.generate_roster(company, roster.start_date, roster.end_date, request.user, roster=roster, only_sites=site_ids or None, only_groups=names)
    messages.success(request, "Regenerated. Pinned shifts and everything outside your selection were kept.")
    return redirect('hr:manage_roster_detail', roster.pk)


@ROSTER_ADMIN
@require_POST
def roster_publish(request, pk):
    roster = get_object_or_404(Roster, pk=pk, company=current_company(request))
    try:
        users, offers_n = R.publish(roster, request.user)
        messages.success(request, f"Published. {users} people notified; {offers_n} shift offer(s) sent to casuals.")
    except RosterError as e:
        messages.error(request, str(e))
    return redirect('hr:manage_roster_detail', roster.pk)


@ROSTER_MANAGER
def shift_edit(request, pk):
    sh = _shift_or_404(request, pk)
    company = current_company(request)
    ranked, excluded, w = R.rank_for(sh, include_casuals=True) if sh.post_id else ([], [], None)
    cand = [w.employees[i] for i in ranked[:25]] if w else []
    blocked = []
    if w:
        for pid, viol in excluded[:40]:
            blocked.append({'employee': w.employees[pid], 'reasons': E.explain(viol), 'overridable': all(c in E.OVERRIDABLE for c, _ in viol)})
    return render(request, 'hr/manage/shift_edit.html', {
        'shift': sh, 'candidates': cand, 'blocked': blocked, 'offers': sh.offers.select_related('employee'),
        'can_override': R.can_override(request.user), 'overrides': sh.overrides.select_related('user')[:10],
        'active': 'roster'})


@ROSTER_MANAGER
@require_POST
def shift_assign(request, pk):
    sh = _shift_or_404(request, pk)
    emp = get_object_or_404(Employee, pk=request.POST.get('employee'), company=current_company(request))
    try:
        v = R.assign_shift(sh, emp, request.user, request.POST.get('override_reason', ''))
        messages.success(request, f"{emp.display_name} placed." + (" Override logged." if v else ""))
    except RosterError as e:
        messages.error(request, str(e))
    return redirect('hr:manage_shift_edit', sh.pk)


@ROSTER_MANAGER
@require_POST
def shift_action(request, pk):
    sh = _shift_or_404(request, pk)
    act = request.POST.get('action')
    try:
        if act == 'unassign':
            R.unassign_shift(sh, request.user)
            messages.success(request, "Removed. The slot is now open.")
        elif act == 'pin':
            R.set_pinned(sh, True)
            messages.success(request, "Pinned: regeneration will not move it.")
        elif act == 'unpin':
            R.set_pinned(sh, False)
        elif act == 'absent':
            rep, sent, excluded = R.mark_absent(sh, request.user, request.POST.get('reason', ''))
            messages.success(request, f"Marked absent. {sent} replacement candidate(s) alerted." + ("" if sent else " Nobody eligible: widen the search."))
            return redirect('hr:manage_shift_edit', rep.pk)
        elif act == 'widen':
            n = R.widen_emergency(sh)
            messages.success(request, f"Alerted {n} more people.")
        elif act == 'offer':
            ranked, _, w = R.rank_for(sh, casuals_only=True)
            n = 0
            for i, pid in enumerate(ranked[:5]):
                ShiftOffer.objects.get_or_create(shift=sh, employee=w.employees[pid], defaults={'kind': 'CASUAL', 'rank': i})
                R._notify_offer(w.employees[pid], sh, False)
                n += 1
            messages.success(request, f"Offered to {n} casual(s).")
        elif act == 'delete':
            if sh.employee_id:
                raise RosterError("Remove the person first.")
            sh.delete()
            messages.success(request, "Deleted.")
            return redirect('hr:manage_roster_detail', sh.roster_id) if sh.roster_id else redirect('hr:manage_roster')
    except RosterError as e:
        messages.error(request, str(e))
    return redirect('hr:manage_shift_edit', sh.pk)


@ROSTER_MANAGER
@require_POST
def shift_add(request, pk):
    """Add an extra shift to a roster by hand."""
    company = current_company(request)
    roster = get_object_or_404(Roster, pk=pk, company=company)
    tmpl = get_object_or_404(ShiftTemplate, pk=request.POST.get('template'), site__in=visible_sites(request.user, company))
    d = _date(request.POST.get('date'))
    post = Post.objects.filter(pk=request.POST.get('post'), site=tmpl.site).first()
    if not d or post is None:
        messages.error(request, "Choose a date, a shift and a post.")
        return redirect('hr:manage_roster_detail', roster.pk)
    sh = Shift.objects.create(roster=roster, employee=None, date=d, start_time=tmpl.start_time, end_time=tmpl.end_time, site=tmpl.site,
                              template=tmpl, post=post, paid_hours=tmpl.paid_hours, source='OPEN',
                              status='PUBLISHED' if roster.status == 'PUBLISHED' else 'DRAFT')
    return redirect('hr:manage_shift_edit', sh.pk)


@ROSTER_MANAGER
def manage_requests(request):
    company = current_company(request)
    sites = visible_sites(request.user, company)
    reqs = ShiftChangeRequest.objects.filter(shift__site__in=sites, status='AWAITING_MANAGER').select_related('employee', 'shift', 'swap_with', 'swap_shift')
    offers = ShiftOffer.objects.filter(shift__site__in=sites, status='ACCEPTED').select_related('employee', 'shift')
    return render(request, 'hr/manage/roster_requests.html', {'reqs': reqs, 'offers': offers, 'active': 'roster'})


@ROSTER_MANAGER
@require_POST
def request_decide(request, pk):
    req = get_object_or_404(ShiftChangeRequest, pk=pk, shift__site__in=visible_sites(request.user, current_company(request)))
    try:
        if request.POST.get('action') == 'approve':
            R.approve_request(req, request.user)
            messages.success(request, "Approved and the roster updated.")
        else:
            R.decline_request(req, request.user, request.POST.get('note', ''))
            messages.success(request, "Declined.")
    except RosterError as e:
        messages.error(request, str(e))
    return redirect('hr:manage_requests')


@ROSTER_MANAGER
@require_POST
def offer_confirm(request, pk):
    offer = get_object_or_404(ShiftOffer, pk=pk, status='ACCEPTED', shift__site__in=visible_sites(request.user, current_company(request)))
    try:
        R.confirm_offer(offer, request.user)
        messages.success(request, "Confirmed.")
    except RosterError as e:
        messages.error(request, str(e))
    return redirect('hr:manage_requests')


@ROSTER_MANAGER
def roster_export(request, pk):
    roster = get_object_or_404(Roster, pk=pk, company=current_company(request))
    data = R.roster_excel(roster)
    resp = HttpResponse(data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="roster-{roster.start_date}.xlsx"'
    audit.log('roster.export', 'roster', request=request, obj=roster)
    return resp


@ROSTER_MANAGER
def roster_print(request, pk):
    company = current_company(request)
    roster = get_object_or_404(Roster, pk=pk, company=company)
    sites = visible_sites(request.user, company)
    site = sites.filter(pk=request.GET.get('site')).first() or sites.first()
    grid = _grid(roster, 'site', Site.objects.filter(pk=site.pk) if site else Site.objects.none())
    return render(request, 'hr/manage/roster_print.html', {'roster': roster, 'site': site, 'grid': grid})


@ROSTER_ADMIN
def roster_reports(request, kind='coverage'):
    company = current_company(request)
    end = _date(request.GET.get('end')) or timezone.localdate()
    start = _date(request.GET.get('start')) or end - timedelta(days=27)
    fns = {
        'coverage': R.report_coverage, 'offdays': R.report_offdays, 'hours': R.report_hours, 'smallgarage': R.report_small_garage,
        'guards': R.report_guard_cover, 'casuals': R.report_casual_usage, 'unfilled': R.report_unfilled,
        'overrides': R.report_overrides, 'breaks': R.report_break_gaps,
    }
    if kind not in fns:
        raise Http404
    rows = fns[kind](company, start, end)
    return render(request, 'hr/manage/roster_reports.html', {
        'kind': kind, 'rows': rows, 'start': start, 'end': end, 'active': 'roster',
        'kinds': [('coverage', 'Coverage by site and shift'), ('offdays', 'Off-days delivered vs required'), ('hours', 'Hours and overtime'),
                  ('smallgarage', 'Small garage duty share'), ('guards', 'Guard cover by building'), ('casuals', 'Casual usage and cost'),
                  ('unfilled', 'Unfilled and emergency shifts'), ('overrides', 'Rule overrides'), ('breaks', 'Lunch and break cover')]})


@ROSTER_ADMIN
def roster_flags(request):
    company = current_company(request)
    return render(request, 'hr/manage/roster_flags.html', {
        'holders': R.flag_holders(company), 'expiring': R.flags_expiring(company, 60), 'active': 'roster'})


@ROSTER_ADMIN
def roster_setup(request):
    company = current_company(request)
    return render(request, 'hr/manage/roster_setup.html', {
        'sites': Site.objects.filter(company=company), 'checks': R.setup_checks(company),
        'summary': None, 'active': 'roster',
        'steps': [('Site', 'sites'), ('POS terminals', 'pos'), ('Staff groups', 'staff-groups'), ('Flags', 'flags'),
                  ('Posts', 'posts'), ('Shifts', 'shift-templates'), ('Open POS', 'open-pos'), ('Demand rules', 'demand-rules'),
                  ('Demand overrides', 'demand-overrides'), ('Required hours', 'required-hours'), ('Roster rules', 'roster-settings'),
                  ('Staff profiles', 'roster-profiles'), ('Staff flags', 'employee-flags'), ('Site approvals', 'site-approvals')]})


@ROSTER_ADMIN
@require_POST
def roster_copy_site(request):
    company = current_company(request)
    src = get_object_or_404(Site, pk=request.POST.get('source'), company=company)
    name = request.POST.get('name', '').strip()
    if not name or Site.objects.filter(company=company, name=name).exists():
        messages.error(request, "Give the new site a name that is not already used.")
        return redirect('hr:manage_roster_setup')
    new = Site.objects.create(company=company, name=name, site_type=src.site_type, open_time=src.open_time, close_time=src.close_time,
                              is_24h=src.is_24h, open_days=src.open_days, setup_minutes=src.setup_minutes, cashup_minutes=src.cashup_minutes,
                              auto_confirm_offers=src.auto_confirm_offers)
    posts_n, tmpl_n = R.copy_site_config(src, new)
    audit.log('roster.copy_site', 'setup', request=request, obj=new, new={'from': src.name, 'posts': posts_n, 'shifts': tmpl_n})
    messages.success(request, f"{name} created with {posts_n} post(s) and {tmpl_n} shift(s) copied. Adjust them, then add approvals.")
    return redirect('hr:manage_roster_setup')


@ROSTER_ADMIN
def roster_import(request):
    """CF-4: staff, flags and site approvals from a spreadsheet (CSV), with a check report before anything is saved."""
    company = current_company(request)
    report, rows_ok = [], []
    if request.method == 'POST' and request.FILES.get('file'):
        text = request.FILES['file'].read().decode('utf-8-sig')
        apply = request.POST.get('apply') == '1'
        groups = {g.name.lower(): g for g in StaffGroup.objects.filter(company=company)}
        flags = {f.name.lower(): f for f in Flag.objects.filter(company=company)}
        sites = {s.name.lower(): s for s in Site.objects.filter(company=company)}
        for i, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
            num = (row.get('employee_number') or '').strip()
            emp = Employee.objects.filter(company=company, employee_number=num).first()
            problems = []
            if emp is None:
                problems.append(f"employee {num!r} not found")
            g = groups.get((row.get('staff_group') or '').strip().lower())
            if (row.get('staff_group') or '').strip() and g is None:
                problems.append(f"staff group {row.get('staff_group')!r} not found")
            fl = []
            for part in (row.get('flags') or '').split(';'):
                part = part.strip()
                if not part:
                    continue
                name, _, exp = part.partition(':')
                f = flags.get(name.strip().lower())
                if f is None:
                    problems.append(f"flag {name!r} not found")
                else:
                    fl.append((f, _date(exp.strip()) if exp else None))
            st = []
            for part in (row.get('sites') or '').split(';'):
                part = part.strip()
                if not part:
                    continue
                s = sites.get(part.lower())
                if s is None:
                    problems.append(f"site {part!r} not found")
                else:
                    st.append(s)
            if problems:
                report.append({'line': i, 'number': num, 'status': 'rejected', 'detail': '; '.join(problems)})
                continue
            report.append({'line': i, 'number': num, 'status': 'ok', 'detail': f"group {g or '-'}, {len(fl)} flag(s), {len(st)} site(s)"})
            rows_ok.append((emp, g, row, fl, st))
        if apply and not [r for r in report if r['status'] == 'rejected']:
            for emp, g, row, fl, st in rows_ok:
                prof, _ = RosterProfile.objects.get_or_create(employee=emp)
                if g:
                    prof.staff_group = g
                if (row.get('weekend_team') or '').strip():
                    prof.weekend_team = row['weekend_team'].strip().upper()[:1]
                prof.save()
                for f, exp in fl:
                    EmployeeFlag.objects.update_or_create(employee=emp, flag=f, defaults={'expires_on': exp, 'granted_by': request.user})
                for s in st:
                    SiteApproval.objects.get_or_create(employee=emp, site=s, post=None)
            audit.log('roster.import', 'setup', request=request, new={'rows': len(rows_ok)})
            messages.success(request, f"Imported {len(rows_ok)} row(s).")
            return redirect('hr:manage_roster_setup')
    return render(request, 'hr/manage/roster_import.html', {'report': report, 'active': 'roster'})

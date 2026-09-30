"""Database side of the roster: loads configuration into the pure engine
(HR.rostering.engine), saves what it produces, and runs the manager and employee
actions (publish, edits, casual offers, swaps, emergency cover, reports)."""
import io
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from ..models import (
    Availability, DemandOverride, DemandRule, Employee, EmployeeFlag, Flag, LeaveRequest, OffDayOwed, OpenPOS, Post,
    PublicHoliday, RequiredHours, Roster, RosterProfile, RosterSettings, RosterVersion, RuleOverride, Shift,
    ShiftAbsence, ShiftChangeRequest, ShiftOffer, ShiftTemplate, SiteApproval, StaffGroup,
    ADMIN_ROLES, HR_ADMIN, SUPER_ADMIN, Site,
)
from ..models.roster import csv_set
from ..rostering import engine as E
from . import audit
from .access import has_role
from .notify import notify


class RosterError(Exception):
    """A rule of the roster was broken. `violations` is a list of (code, message)."""

    def __init__(self, message, violations=None):
        super().__init__(message)
        self.violations = violations or []


@contextmanager
def month_basis(settings_row):
    """MH-9: count hours per calendar month or per pay period."""
    old = E.MONTH_START_DAY
    E.MONTH_START_DAY = settings_row.pay_period_start_day if settings_row.month_basis == 'PAY_PERIOD' else 1
    try:
        yield
    finally:
        E.MONTH_START_DAY = old


def get_settings(company):
    return RosterSettings.objects.get_or_create(company=company)[0]


def display(emp):
    return emp.display_name if emp else 'Open shift'


# ------------------------------------------------------------------ loading the world
class World:
    pass


def _required_hours_table(groups, employees, keys):
    """MH-1/MH-2: figure per (employee, month key), person override first, then the group's effective-dated figure."""
    rows = list(RequiredHours.objects.all())
    by_emp, by_group = defaultdict(list), defaultdict(list)
    for r in rows:
        if r.employee_id:
            by_emp[r.employee_id].append(r)
        elif r.staff_group_id:
            by_group[r.staff_group_id].append(r)
    out = {}
    for emp in employees:
        prof = emp.roster_profile
        grp = prof.staff_group
        if grp is None or grp.is_casual:
            continue
        for key in keys:
            first, _ = E.month_bounds(key)
            days = E.key_days(key)
            src = None
            for r in sorted(by_emp.get(emp.id, []), key=lambda r: (r.effective_from, r.id), reverse=True):
                if r.effective_from <= first:
                    src = (r.hours_30_31, r.hours_february)
                    break
            if src is None:
                for r in sorted(by_group.get(grp.id, []), key=lambda r: (r.effective_from, r.id), reverse=True):
                    if r.effective_from <= first:
                        src = (r.hours_30_31, r.hours_february)
                        break
            if src is None:
                src = (grp.hours_30_31, grp.hours_february)
            long_h, feb_h = float(src[0]), (float(src[1]) if src[1] is not None else None)
            if days >= 30:
                out[(emp.id, key)] = long_h
            else:
                out[(emp.id, key)] = feb_h if feb_h is not None else E.default_month_hours(days, long_h)
    return out


def load_world(company, start, end, history_days=14):
    """Load everything the engine needs for [start, end]. Engine ids are database ids."""
    w = World()
    w.company, w.start, w.end = company, start, end
    w.settings = get_settings(company)
    w.rules = w.settings.engine_rules()
    sites = list(Site.objects.filter(company=company, is_active=True))
    w.db_sites = {s.id: s for s in sites}
    w.sites = [E.Site(s.id, s.name, s.site_type, s.open_time or time(0), s.close_time or time(23, 59), s.is_24h,
                      s.open_day_numbers, s.setup_minutes, s.cashup_minutes) for s in sites]
    db_posts = list(Post.objects.filter(site__in=sites, is_active=True).prefetch_related('staff_groups', 'alt_groups', 'required_flags'))
    w.db_posts = {p.id: p for p in db_posts}
    w.posts = [E.Post(p.id, p.site_id, p.name, {g.name for g in p.staff_groups.all()}, {g.name for g in p.alt_groups.all()},
                      {f.name for f in p.required_flags.all()}, p.continuous_cover, p.fair_share) for p in db_posts]
    db_templates = list(ShiftTemplate.objects.filter(site__in=sites, is_active=True))
    w.db_templates = {t.id: t for t in db_templates}
    w.templates = [E.Template(t.id, t.site_id, t.name, t.start_time, t.end_time, float(t.paid_hours), t.day_type_set,
                              t.break_type, t.break_minutes, t.pay_weekend) for t in db_templates]
    w.template_active = {t.id: (t.effective_from, t.effective_to) for t in db_templates}
    w.demand = [E.DemandRule(r.id, r.site_id, r.template_id, r.post_id, r.rule_type, r.minimum, r.target, r.maximum,
                             csv_set(r.day_types) or set(E.DAY_TYPES), r.priority, r.effective_from, r.effective_to, r.per_unit)
                for r in DemandRule.objects.filter(site__in=sites)]
    w.overrides = [E.DemandOverride(o.site_id, o.start_date, o.end_date, o.minimum, o.target, o.maximum, o.template_id, o.post_id)
                   for o in DemandOverride.objects.filter(site__in=sites, end_date__gte=start, start_date__lte=end)]
    w.open_pos = {(o.template_id, o.day_type): o.count for o in OpenPOS.objects.filter(template__in=db_templates)}
    w.holidays = set(PublicHoliday.objects.filter(company=company, date__range=(start, end)).values_list('date', flat=True))

    emps = list(Employee.objects.filter(company=company, status='ACTIVE', roster_profile__staff_group__isnull=False)
                .select_related('roster_profile', 'roster_profile__staff_group'))
    w.employees = {e.id: e for e in emps}
    flags = defaultdict(dict)
    for ef in EmployeeFlag.objects.filter(employee__in=emps).select_related('flag'):
        flags[ef.employee_id][ef.flag.name] = (ef.effective_from, ef.expires_on)
    approvals = defaultdict(set)
    for a in SiteApproval.objects.filter(employee__in=emps):
        approvals[a.employee_id].add((a.site_id, a.post_id))
    leave = defaultdict(set)
    for lr in LeaveRequest.objects.filter(employee__in=emps, status__in=('APPROVED', 'CANCEL_REQUESTED'),
                                          end_date__gte=start - timedelta(days=1), start_date__lte=end + timedelta(days=1)):
        for d in E.daterange(max(lr.start_date, start - timedelta(days=1)), min(lr.end_date, end + timedelta(days=1))):
            leave[lr.employee_id].add(d)
    unavailable = defaultdict(set)
    for av in Availability.objects.filter(employee__in=emps, available=False, from_time__isnull=True):
        unavailable[av.employee_id].add(av.weekday)
    hist = defaultdict(list)
    hist_shifts = Shift.objects.filter(employee__in=emps, date__range=(start - timedelta(days=history_days), start - timedelta(days=1))) \
        .exclude(status__in=('CANCELLED', 'ABSENT'))
    last_weekend = {}
    for sh in hist_shifts:
        hist[sh.employee_id].append((sh.start_at, sh.end_at))
    for sh in Shift.objects.filter(employee__in=emps, date__lt=start, source='PATTERN', date__gte=start - timedelta(days=60)) \
            .exclude(status__in=('CANCELLED', 'ABSENT')):
        if sh.date.weekday() >= 5:
            sat = sh.date - timedelta(days=sh.date.weekday() - 5)
            if sat > last_weekend.get(sh.employee_id, date.min):
                last_weekend[sh.employee_id] = sat
    keys = sorted({E.month_key(d) for d in E.daterange(start, end)})
    req = _required_hours_table(None, emps, keys)
    w.people = []
    for e in emps:
        prof, grp = e.roster_profile, e.roster_profile.staff_group
        rh = {}
        for k in keys:
            v = req.get((e.id, k))
            if v is None:
                continue
            first, last = E.month_bounds(k)
            if w.settings.leave_counts_toward_hours and leave[e.id]:                 # MH-5: leave counts toward hours
                days = [d for d in E.daterange(first, last) if d in leave[e.id]]
                v = max(0.0, v - len(days) * v / E.key_days(k))
            # part of a month only: scale by the share inside the period
            inside = len([d for d in E.daterange(max(first, start), min(last, end))])
            if inside < E.key_days(k):
                v = v * inside / E.key_days(k)
            rh[k] = round(v, 1)
        rules = None
        if grp.max_consecutive_days or grp.min_off_days_per_week != w.rules.min_off_days_per_week:
            rules = E.Rules(**{**w.rules.__dict__, 'max_consecutive_days': grp.max_consecutive_days or w.rules.max_consecutive_days,
                               'min_off_days_per_week': grp.min_off_days_per_week})
        w.people.append(E.Person(
            e.id, e.display_name, grp.name, grp.pattern_based, grp.is_casual, flags[e.id], approvals[e.id], leave[e.id],
            unavailable[e.id], rh, prof.weekend_team or None, last_weekend.get(e.id),
            float(prof.weekly_hours_cap) if prof.weekly_hours_cap else None, hist[e.id], prof.casual_priority, rules))
    w.groups = {g.id: g for g in StaffGroup.objects.filter(company=company)}
    return w


def _slots(w, only_sites=None, only_groups=None):
    slots = E.build_slots(w.start, w.end, w.sites, w.templates, w.posts, w.demand, w.overrides, w.open_pos, w.holidays, w.template_active)
    if only_sites:
        slots = [s for s in slots if s.site_id in only_sites]
    if only_groups:
        names = set(only_groups)
        pb = {p.id: p for p in w.posts}
        slots = [s for s in slots if not pb[s.post_id].groups or pb[s.post_id].groups & names or pb[s.post_id].alt_groups & names]
    return slots


def demand_summary(company, start, end):
    """DR-7: what the period needs, per site, shift and post, before generating."""
    w = load_world(company, start, end)
    with month_basis(w.settings):
        slots = _slots(w)
    sm = E.demand_summary(slots)
    rows = []
    for (site, tmpl, post), v in sorted(sm.items()):
        rows.append({'site': w.db_sites[site].name, 'shift': w.db_templates[tmpl].name, 'post': w.db_posts[post].name,
                     'required': v['required'], 'target': v['target']})
    return rows


def feasibility_check(company, start, end, whatif=None):
    """Staffing feasibility, with optional what-if changes (Section 8): {'pos_open': n, 'remove': [employee ids]}."""
    w = load_world(company, start, end)
    whatif = whatif or {}
    with month_basis(w.settings):
        if whatif.get('pos_open') is not None:
            for k in list(w.open_pos):
                w.open_pos[k] = int(whatif['pos_open'])
        people = [p for p in w.people if p.id not in set(whatif.get('remove') or [])]
        slots = _slots(w)
        fz = E.feasibility(people, w.posts, slots, w.rules)
    names = {p.id: p.name for p in w.posts}
    fz['lines'] = [{**l, 'site_name': w.db_sites[l['site']].name, 'post_name': names[l['post']]} for l in fz['lines']]
    return fz


# ------------------------------------------------------------------ generation
def _assignment_from_shift(sh: Shift):
    key = (sh.date, sh.site_id, sh.template_id, sh.post_id, sh.slot_index)
    return E.Assignment(sh.employee_id, sh.date, sh.site_id, sh.template_id, sh.post_id, sh.start_at, sh.end_at,
                        float(sh.paid_hours), sh.night_minutes, True, sh.source, key)


def _warning_dict(x):
    return {'code': x.code, 'message': x.message, 'date': x.date.isoformat() if x.date else None,
            'person': x.person_id, 'site': x.site_id}


@transaction.atomic
def generate_roster(company, start, end, user=None, roster=None, only_sites=None, only_groups=None):
    """Build a draft roster (RG-1). On an existing roster, pinned shifts and everything outside the chosen
    sites/groups are kept and only the rest is regenerated (RG-7)."""
    w = load_world(company, start, end)
    if roster is None:
        roster = Roster.objects.create(company=company, start_date=start, end_date=end, created_by=user)
    only_sites = set(only_sites or [])
    with month_basis(w.settings):
        slots = _slots(w, only_sites, only_groups)
        # what stays: pinned shifts, published shifts, and anything outside the regeneration scope
        keep_qs = roster.shifts.exclude(status='CANCELLED')
        existing = list(keep_qs)
        scope_groups = set(only_groups or [])
        pb = {p.id: p for p in w.posts}
        def in_scope(sh):
            if only_sites and sh.site_id not in only_sites:
                return False
            if scope_groups:
                p = pb.get(sh.post_id)
                return bool(p and (not p.groups or p.groups & scope_groups or p.alt_groups & scope_groups))
            return True
        drop = [sh.id for sh in existing if not sh.pinned and sh.status == 'DRAFT' and in_scope(sh)]
        Shift.objects.filter(id__in=drop).delete()
        kept = [sh for sh in existing if sh.id not in set(drop)]
        pinned = [_assignment_from_shift(sh) for sh in kept if sh.employee_id]
        # pattern-based groups first (RG-9)
        all_assign, warnings, report = [], [], {}
        created = []
        for grp in w.groups.values():
            if not grp.pattern_based or not grp.weekday_template_id or not grp.pattern_site_id or not grp.pattern_post_id:
                continue
            if only_groups and grp.name not in scope_groups:
                continue
            tw = next((t for t in w.templates if t.id == grp.weekday_template_id), None)
            te = next((t for t in w.templates if t.id == grp.weekend_template_id), None) if grp.weekend_template_id else None
            if tw is None:
                continue
            cfg = E.PatternConfig(grp.name, grp.pattern_site_id, grp.pattern_post_id, tw, te,
                                  tuple(int(x) for x in grp.weekend_days.split(',') if x.strip().isdigit()) or (5,),
                                  grp.weekend_mode, grp.min_on_duty_per_weekend, tuple(sorted(company.work_day_numbers)) or (0, 1, 2, 3, 4),
                                  grp.weekend_rotation_weeks)
            out, warns, rep = E.plan_pattern([p for p in w.people if p.group == grp.name], cfg, start, end, w.rules, w.holidays, w.posts)
            all_assign += out
            warnings += warns
            report[grp.name] = rep
        people = [p for p in w.people]
        res = E.generate(people, w.posts, slots, w.rules, pinned=pinned)
        warnings += res.warnings
        fz = E.feasibility([p for p in people], w.posts, slots, w.rules)
        for a in res.assignments:
            if a.pinned:
                continue
            all_assign.append(a)
        # save
        optional_keys = {sl.key for sl in slots if not sl.required}
        objs = []
        for a in all_assign:
            objs.append(Shift(
                roster=roster, employee_id=a.person_id, date=a.date, start_time=a.start.time(), end_time=a.end.time(),
                site_id=a.site_id, template_id=a.template_id, post_id=a.post_id, slot_index=a.slot_key[4] if a.slot_key else 0,
                required=a.slot_key not in optional_keys, paid_hours=a.paid, night_minutes=a.night_min, pinned=False,
                source='OPEN' if a.person_id is None else a.source, status='DRAFT'))
        Shift.objects.bulk_create(objs)
        req_open = res.stats['unfilled_required']
        roster.warnings = [_warning_dict(x) for x in warnings]
        roster.quality_score = res.stats['score']
        roster.summary = {
            'unfilled_required': req_open, 'unfilled_total': res.stats['unfilled_total'], 'people': len(people),
            'feasible': fz['ok'], 'feasibility': fz['summary'],
            'hours': [{'person': r['person'], 'month': f"{r['month'][0]}-{r['month'][1]:02d}", 'scheduled': r['scheduled'],
                       'required': r['required']} for r in res.stats['hours']],
            'weekends': report,
        }
        roster.save()
    audit.log('roster.generate', 'roster', user=user, obj=roster, new={'score': float(roster.quality_score), 'unfilled': req_open})
    return roster


# ------------------------------------------------------------------ checking a single placement
def _person_for(w, employee_id):
    return next((p for p in w.people if p.id == employee_id), None)


def check_placement(shift, employee, ignore_month=True):
    """Would `employee` be allowed in `shift`, given their other shifts? Returns [(code, message)]."""
    company = employee.company
    d0, d1 = shift.date - timedelta(days=14), shift.date + timedelta(days=14)
    w = load_world(company, shift.date, shift.date)
    p = _person_for(w, employee.id)
    if p is None:
        return [('GROUP_NOT_ALLOWED', 'has no roster staff group')]
    others = Shift.objects.filter(employee=employee, date__range=(d0, d1)).exclude(pk=shift.pk).exclude(status__in=('CANCELLED', 'ABSENT'))
    p.history = []
    assigned = [(s.start_at, s.end_at, float(s.paid_hours), s.night_minutes) for s in others]
    slot = E.Slot((shift.date, shift.site_id, shift.template_id, shift.post_id, shift.slot_index), shift.date, shift.site_id,
                  shift.template_id, shift.post_id, shift.slot_index, True, 0, shift.start_at, shift.end_at, float(shift.paid_hours), shift.night_minutes)
    posts_by = {x.id: x for x in w.posts}
    if shift.post_id not in posts_by:
        return []
    with month_basis(w.settings):
        return E.hard_violations(p, slot, assigned, p.rules or w.rules, posts_by, ignore_month=ignore_month)


def can_override(user):
    return user is not None and has_role(user, HR_ADMIN, SUPER_ADMIN)


def assign_shift(shift, employee, user, override_reason='', source='MANUAL'):
    """MR-4/MR-5: manager places someone. Eligibility breaches can never be overridden; other hard rules need
    override permission and a reason, and are logged (OD-4)."""
    v = check_placement(shift, employee) if employee else []
    if v:
        blocking = [x for x in v if x[0] not in E.OVERRIDABLE]
        if blocking:
            raise RosterError("Blocked: " + E.explain(blocking), v)
        if not can_override(user):
            raise RosterError("Blocked: " + E.explain(v) + ". A manager with override permission can allow this with a reason.", v)
        if not override_reason.strip():
            raise RosterError("A reason is required to override: " + E.explain(v), v)
    with transaction.atomic():
        old = shift.employee
        shift.employee = employee
        shift.source = source
        shift.freed_from = None
        if shift.status == 'ABSENT':
            shift.status = 'PUBLISHED'
        shift.save()
        for code, msg in v:
            RuleOverride.objects.create(roster=shift.roster, shift=shift, employee=employee, rule_code=code, detail=msg[:300],
                                        reason=override_reason.strip()[:300], user=user)
        audit.log('roster.assign', 'roster', user=user, obj=shift, employee=employee,
                  old={'employee': display(old)}, new={'employee': display(employee), 'override': [c for c, _ in v]})
        if shift.roster and shift.roster.status == 'PUBLISHED':
            _bump_version(shift.roster, user, f"{display(employee)} placed on {shift.date:%d %b} {shift.start_time:%H:%M}" +
                          (f" (override: {override_reason.strip()})" if v else ''))
            if employee and employee.user:
                notify([employee.user], 'roster', "Your roster changed", f"You are now on {shift.date:%a %d %b} {shift.start_time:%H:%M}-{shift.end_time:%H:%M}.", reverse('hr:roster'))
    return v


def unassign_shift(shift, user):
    old = shift.employee
    shift.employee = None
    shift.source = 'OPEN'
    shift.save()
    audit.log('roster.unassign', 'roster', user=user, obj=shift, employee=old)
    if shift.roster and shift.roster.status == 'PUBLISHED':
        _bump_version(shift.roster, user, f"{display(old)} removed from {shift.date:%d %b}")


def set_pinned(shift, pinned=True):
    shift.pinned = pinned
    shift.save(update_fields=['pinned'])


# ------------------------------------------------------------------ publishing and versions
def _snapshot(roster):
    return [{'id': s.id, 'employee': s.employee_id, 'date': s.date.isoformat(), 'start': s.start_time.strftime('%H:%M'),
             'end': s.end_time.strftime('%H:%M'), 'site': s.site_id, 'post': s.post_id, 'template': s.template_id,
             'status': s.status, 'source': s.source} for s in roster.shifts.all()]


def _bump_version(roster, user, reason):
    roster.version += 1
    roster.save(update_fields=['version'])
    RosterVersion.objects.create(roster=roster, version=roster.version, reason=reason[:250], snapshot=_snapshot(roster), created_by=user)


@transaction.atomic
def publish(roster, user):
    """MR-7: lock the roster, notify everyone affected, store a version, and offer open shifts to casuals."""
    if roster.status == 'PUBLISHED':
        raise RosterError("This roster is already published.")
    for old in Roster.objects.filter(company=roster.company, status='PUBLISHED', start_date=roster.start_date, end_date=roster.end_date):
        old.status = 'ARCHIVED'
        old.save(update_fields=['status'])
    roster.shifts.filter(status='DRAFT').update(status='PUBLISHED')
    roster.status, roster.published_at, roster.published_by = 'PUBLISHED', timezone.now(), user
    roster.save()
    RosterVersion.objects.create(roster=roster, version=roster.version, reason='Published', snapshot=_snapshot(roster), created_by=user)
    users = {s.employee.user for s in roster.shifts.select_related('employee__user') if s.employee_id and s.employee.user_id}
    notify(list(users), 'roster', "Your roster is published", f"{roster.start_date:%d %b} to {roster.end_date:%d %b %Y}.", reverse('hr:roster'))
    n = send_casual_offers(roster, user)
    audit.log('roster.publish', 'roster', user=user, obj=roster, new={'notified': len(users), 'offers': n})
    return len(users), n


def edit_published(shift, user, reason, **changes):
    """MR-7: a later edit needs a reason and respects the minimum notice; both versions are kept."""
    if not reason.strip():
        raise RosterError("A reason is required to edit a published roster.")
    st = get_settings(shift.roster.company) if shift.roster else None
    if st and shift.start_at - datetime.now() < timedelta(hours=st.min_notice_hours) and not can_override(user):
        raise RosterError(f"Changes need at least {st.min_notice_hours} hours notice; a manager with override permission can allow it.")
    for k, v in changes.items():
        setattr(shift, k, v)
    shift.save()
    _bump_version(shift.roster, user, reason)
    audit.log('roster.edit_published', 'roster', user=user, obj=shift, new=changes, description=reason)


# ------------------------------------------------------------------ casual call-out (CW)
def _roster_assignments(w, start, end, exclude_shift=None):
    qs = Shift.objects.filter(date__range=(start - timedelta(days=14), end + timedelta(days=14))).exclude(status__in=('CANCELLED', 'ABSENT'))
    if exclude_shift is not None:
        qs = qs.exclude(pk=exclude_shift.pk)
    return [E.Assignment(s.employee_id, s.date, s.site_id, s.template_id, s.post_id, s.start_at, s.end_at, float(s.paid_hours),
                         s.night_minutes) for s in qs if s.employee_id]


def rank_for(shift, casuals_only=False, include_casuals=True, limit=None):
    """Ranked replacement candidates for a shift plus the reasons others were excluded (SC-6)."""
    w = load_world(shift.roster.company if shift.roster else shift.site.company, shift.date, shift.date)
    people = [p for p in w.people if (p.casual if casuals_only else True)]
    roster = _roster_assignments(w, shift.date, shift.date, exclude_shift=shift)
    absent = E.Assignment(shift.employee_id, shift.date, shift.site_id, shift.template_id, shift.post_id, shift.start_at, shift.end_at,
                          float(shift.paid_hours), shift.night_minutes)
    with month_basis(w.settings):
        ranked, excluded = E.rank_replacements(people, {p.id: p for p in w.posts}, w.rules, absent, roster, include_casuals=include_casuals)
    if limit:
        ranked = ranked[:limit]
    return ranked, excluded, w


def send_casual_offers(roster, user=None, per_shift=3):
    """CW-4/CW-5: open shifts go to eligible casuals, fewest hours this month first (or the set priority)."""
    n = 0
    now = timezone.localdate()
    for sh in roster.shifts.filter(employee__isnull=True, required=True, status__in=('DRAFT', 'PUBLISHED'), date__gte=now):
        if sh.offers.exists():
            continue
        ranked, _, w = rank_for(sh, casuals_only=True)
        for i, pid in enumerate(ranked[:per_shift]):
            emp = w.employees[pid]
            ShiftOffer.objects.create(shift=sh, employee=emp, kind='CASUAL', rank=i)
            _notify_offer(emp, sh, False)
            n += 1
    return n


def _notify_offer(emp, sh, urgent):
    pay = ''
    prof = getattr(emp, 'roster_profile', None)
    if prof and prof.casual_rate:
        pay = f" Pay: R{prof.casual_rate} per {prof.get_casual_pay_basis_display().lower().replace('per ', '')}."
    if emp.user:
        notify([emp.user], 'roster', ("URGENT: " if urgent else "") + "Shift offered",
               f"{sh.site} {sh.post.name if sh.post else ''} {sh.date:%a %d %b} {sh.start_time:%H:%M}-{sh.end_time:%H:%M}.{pay}",
               reverse('hr:roster_offers'))


@transaction.atomic
def respond_offer(offer, accept, user=None):
    """First eligible acceptance is confirmed (or held for a manager, per site)."""
    if offer.status != 'OFFERED':
        raise RosterError("This offer is no longer open.")
    sh = offer.shift
    offer.responded_at = timezone.now()
    if not accept:
        offer.status = 'DECLINED'
        offer.save()
        return offer
    if sh.employee_id is not None:
        offer.status = 'LOST'
        offer.save()
        raise RosterError("Someone else already took this shift.")
    v = check_placement(sh, offer.employee, ignore_month=True)
    blocking = [x for x in v if x[0] not in ('CASUAL_CAP',) or True]
    if v:
        offer.status = 'DECLINED'
        offer.save()
        raise RosterError("You can no longer take this shift: " + E.explain(v), v)
    offer.status = 'ACCEPTED'
    offer.save()
    auto = sh.site.auto_confirm_offers if sh.site else True
    if auto:
        confirm_offer(offer, user)
    else:
        notify(_manager_users(), 'roster', "Shift offer accepted", f"{offer.employee.display_name} accepted {sh.date:%d %b}. Confirm to assign.", reverse('hr:manage_roster'))
    return offer


@transaction.atomic
def confirm_offer(offer, user=None):
    sh = offer.shift
    if sh.employee_id is not None:
        raise RosterError("This shift is already filled.")
    sh.employee = offer.employee
    sh.source = 'EMERGENCY' if offer.kind == 'EMERGENCY' else 'CASUAL'
    if sh.status == 'ABSENT':
        sh.status = 'PUBLISHED'
    sh.save()
    offer.status = 'CONFIRMED'
    offer.save()
    sh.offers.exclude(pk=offer.pk).filter(status__in=('OFFERED', 'ACCEPTED')).update(status='LOST')
    if sh.roster and sh.roster.status == 'PUBLISHED':
        _bump_version(sh.roster, user, f"{offer.employee.display_name} confirmed for {sh.date:%d %b}")
    if offer.employee.user:
        notify([offer.employee.user], 'roster', "Shift confirmed", f"{sh.date:%a %d %b} {sh.start_time:%H:%M}-{sh.end_time:%H:%M}", reverse('hr:roster'))
    audit.log('roster.offer_confirmed', 'roster', user=user, obj=sh, employee=offer.employee)


def _manager_users():
    from ..models import RoleAssignment
    return [ra.user for ra in RoleAssignment.objects.filter(role__in=(HR_ADMIN, SUPER_ADMIN)).select_related('user')]


# ------------------------------------------------------------------ absence and emergency cover (SC-6..SC-9)
@transaction.atomic
def mark_absent(shift, user, reason='', wave=5):
    """The person did not arrive: free the slot, rank replacements, alert the top candidates."""
    if shift.employee_id is None:
        raise RosterError("This shift has no one on it.")
    absent_emp = shift.employee
    ShiftAbsence.objects.create(shift=shift, employee=absent_emp, reason=reason[:200], marked_by=user)
    replacement = Shift.objects.create(
        roster=shift.roster, employee=None, date=shift.date, start_time=shift.start_time, end_time=shift.end_time, site=shift.site,
        template=shift.template, post=shift.post, slot_index=shift.slot_index, required=True, paid_hours=shift.paid_hours,
        night_minutes=shift.night_minutes, source='OPEN', status='PUBLISHED', note=f"Cover for {absent_emp.display_name}")
    shift.status = 'ABSENT'
    shift.save(update_fields=['status'])
    urgent = bool(shift.post and shift.post.continuous_cover)
    ranked, excluded, w = rank_for(replacement, include_casuals=True)
    sent = 0
    for i, pid in enumerate(ranked[:wave]):
        emp = w.employees[pid]
        ShiftOffer.objects.create(shift=replacement, employee=emp, kind='EMERGENCY', urgent=urgent, rank=i)
        _notify_offer(emp, replacement, urgent)
        sent += 1
    if urgent or sent == 0:
        notify(_manager_users(), 'roster', ("URGENT " if urgent else "") + "Cover needed",
               f"{absent_emp.display_name} absent {shift.date:%a %d %b} {shift.start_time:%H:%M}. {sent} candidates alerted."
               + ("" if sent else " Nobody is eligible: widen the search."), reverse('hr:manage_roster'))
    audit.log('roster.absent', 'roster', user=user, obj=shift, employee=absent_emp, description=reason,
              new={'urgent': urgent, 'alerted': sent})
    return replacement, sent, excluded


def widen_emergency(shift, n=5):
    """No one accepted: alert the next candidates (the casual pool comes after permanent staff)."""
    done = set(shift.offers.values_list('employee_id', flat=True))
    ranked, _, w = rank_for(shift, include_casuals=True)
    fresh = [p for p in ranked if p not in done][:n]
    urgent = bool(shift.post and shift.post.continuous_cover)
    base = shift.offers.count()
    for i, pid in enumerate(fresh):
        ShiftOffer.objects.create(shift=shift, employee=w.employees[pid], kind='EMERGENCY', urgent=urgent, rank=base + i)
        _notify_offer(w.employees[pid], shift, urgent)
    return len(fresh)


def record_off_day_worked(employee, day):
    """SC-9: someone who works a required off-day at short notice is owed that day back."""
    return OffDayOwed.objects.create(employee=employee, worked_on=day)


# ------------------------------------------------------------------ shift change requests (Section 10.1)
def _now():
    return datetime.now()


@transaction.atomic
def request_change(employee, shift, kind, swap_shift=None, reason='', new_start=None, new_end=None):
    st = get_settings(employee.company)
    if shift.employee_id != employee.id or shift.status != 'PUBLISHED':
        raise RosterError("You can only change your own published shifts.")
    if shift.start_at - _now() < timedelta(hours=st.min_notice_hours):
        raise RosterError(f"Requests must be made at least {st.min_notice_hours} hours before the shift.")
    if shift.change_requests.filter(status__in=('REQUESTED', 'AWAITING_COLLEAGUE', 'AWAITING_MANAGER')).exists():
        raise RosterError("There is already an open request for this shift.")
    problems = []
    partner = None
    if kind == 'SWAP':
        if swap_shift is None or swap_shift.employee_id is None or swap_shift.employee_id == employee.id:
            raise RosterError("Choose a colleague's shift to swap with.")
        partner = swap_shift.employee
        # SC-1: rules check for everybody involved, in both directions
        for who, target, other in ((employee, swap_shift, shift), (partner, shift, swap_shift)):
            v = _check_swapped(who, target, other)
            if v:
                problems.append(f"{who.display_name}: {E.explain(v)}")
        if problems:
            raise RosterError("Blocked by the rules check. " + " | ".join(problems))
    elif kind == 'CHANGE':
        if not (new_start and new_end and new_start != new_end):
            raise RosterError("Give the new start and end time.")
    req = ShiftChangeRequest.objects.create(
        shift=shift, employee=employee, kind=kind, swap_with=partner, swap_shift=swap_shift, reason=reason[:255],
        new_start=new_start, new_end=new_end,
        status='AWAITING_COLLEAGUE' if kind == 'SWAP' else 'AWAITING_MANAGER',
        expires_at=timezone.now() + timedelta(hours=st.request_expiry_hours))
    if kind == 'SWAP' and partner.user:
        notify([partner.user], 'roster', "Swap request",
               f"{employee.display_name} asks to swap {shift.date:%a %d %b} for your {swap_shift.date:%a %d %b}.", reverse('hr:roster'))
    else:
        notify(_manager_users(), 'roster', "Shift change request", f"{employee.display_name}: {req.get_kind_display()} on {shift.date:%d %b}", reverse('hr:manage_roster'))
    audit.log('roster.request', 'roster', obj=req, employee=employee, new={'kind': kind})
    return req


def _check_swapped(who, target_shift, own_shift):
    """`who` moves from own_shift to target_shift: check target against their other shifts without own_shift."""
    d0, d1 = target_shift.date - timedelta(days=14), target_shift.date + timedelta(days=14)
    w = load_world(who.company, target_shift.date, target_shift.date)
    p = _person_for(w, who.id)
    if p is None:
        return [('GROUP_NOT_ALLOWED', 'has no roster staff group')]
    others = Shift.objects.filter(employee=who, date__range=(d0, d1)).exclude(pk=own_shift.pk).exclude(pk=target_shift.pk) \
        .exclude(status__in=('CANCELLED', 'ABSENT'))
    p.history = []
    assigned = [(s.start_at, s.end_at, float(s.paid_hours), s.night_minutes) for s in others]
    slot = E.Slot((target_shift.date, target_shift.site_id, target_shift.template_id, target_shift.post_id, 0), target_shift.date,
                  target_shift.site_id, target_shift.template_id, target_shift.post_id, 0, True, 0, target_shift.start_at,
                  target_shift.end_at, float(target_shift.paid_hours), target_shift.night_minutes)
    with month_basis(w.settings):
        return E.hard_violations(p, slot, assigned, p.rules or w.rules, {x.id: x for x in w.posts}, ignore_month=True)


@transaction.atomic
def colleague_respond(req, accept, user=None):
    if req.status != 'AWAITING_COLLEAGUE':
        raise RosterError("This request is not waiting for you.")
    if not accept:
        req.status = 'DECLINED'
        req.decision_note = 'Declined by colleague'
        req.save()
        _notify_requester(req, 'Your swap was declined by your colleague.')
        return req
    st = get_settings(req.employee.company)
    if st.swap_auto_approve:
        return approve_request(req, None, auto=True)
    req.status = 'AWAITING_MANAGER'
    req.save()
    notify(_manager_users(), 'roster', "Swap awaiting approval", f"{req.employee.display_name} and {req.swap_with.display_name}", reverse('hr:manage_roster'))
    return req


@transaction.atomic
def approve_request(req, user, auto=False):
    if req.status not in ('AWAITING_MANAGER', 'AWAITING_COLLEAGUE'):
        raise RosterError("This request is not open.")
    sh = req.shift
    if sh is None:
        raise RosterError("The shift no longer exists.")
    if req.kind == 'SWAP':
        other = req.swap_shift
        for who, target, own in ((req.employee, other, sh), (req.swap_with, sh, other)):
            v = _check_swapped(who, target, own)
            if v:
                raise RosterError(f"{who.display_name} no longer passes the rules: " + E.explain(v), v)
        a, b = sh.employee_id, other.employee_id
        sh.employee_id, other.employee_id = b, a
        sh.source = other.source = 'SWAP'
        sh.save()
        other.save()
    elif req.kind == 'CHANGE':
        sh.start_time, sh.end_time = req.new_start, req.new_end
        sh.save()
    elif req.kind in ('OFF', 'GIVEAWAY'):
        sh.employee = None
        sh.source = 'OPEN'
        sh.save()
        if sh.roster:
            ranked, _, w = rank_for(sh, include_casuals=True)
            for i, pid in enumerate(ranked[:5]):
                ShiftOffer.objects.create(shift=sh, employee=w.employees[pid], kind='CASUAL', rank=i)
                _notify_offer(w.employees[pid], sh, False)
    req.status, req.decided_by = 'APPROVED', user
    req.save()
    if sh.roster and sh.roster.status == 'PUBLISHED':
        _bump_version(sh.roster, user, f"{req.get_kind_display()}: {req.employee.display_name} {sh.date:%d %b}")
    _notify_requester(req, 'Your shift change was approved.' + (' (automatically)' if auto else ''))
    audit.log('roster.request_approved', 'roster', user=user, obj=req, employee=req.employee)
    return req


def decline_request(req, user, note):
    if not note.strip():
        raise RosterError("Give a reason for declining.")
    req.status, req.decision_note, req.decided_by = 'DECLINED', note, user
    req.save()
    _notify_requester(req, f"Your shift change was declined: {note}")


def cancel_request(req):
    if req.status in ('APPROVED', 'DECLINED', 'EXPIRED', 'CANCELLED'):
        raise RosterError("This request is already closed.")
    req.status = 'CANCELLED'
    req.save()


def expire_requests_and_offers():
    """SC-3: unanswered requests and offers expire and return to the requester. Run from a scheduled task."""
    now = timezone.now()
    n = 0
    for r in ShiftChangeRequest.objects.filter(status__in=('REQUESTED', 'AWAITING_COLLEAGUE', 'AWAITING_MANAGER'), expires_at__lt=now):
        r.status = 'EXPIRED'
        r.save()
        _notify_requester(r, "Your shift change request expired without an answer.")
        n += 1
    for o in ShiftOffer.objects.filter(status='OFFERED', shift__date__lt=timezone.localdate()):
        o.status = 'EXPIRED'
        o.save()
        n += 1
    return n


def _notify_requester(req, message):
    if req.employee.user:
        notify([req.employee.user], 'roster', 'Shift change', message, reverse('hr:roster'))


# ------------------------------------------------------------------ leave integration (OP-3)
@transaction.atomic
def on_leave_approved(leave_request):
    """Approved leave frees the slot and re-offers it; the person is no longer shown as working."""
    freed = 0
    for sh in Shift.objects.filter(employee=leave_request.employee, date__range=(leave_request.start_date, leave_request.end_date),
                                   status__in=('DRAFT', 'PUBLISHED')):
        sh.freed_from, sh.employee, sh.source = leave_request.employee, None, 'OPEN'
        sh.save()
        freed += 1
        if sh.roster and sh.roster.status == 'PUBLISHED' and sh.post_id:
            ranked, _, w = rank_for(sh, casuals_only=True)
            for i, pid in enumerate(ranked[:3]):
                ShiftOffer.objects.create(shift=sh, employee=w.employees[pid], kind='CASUAL', rank=i)
                _notify_offer(w.employees[pid], sh, False)
    if freed:
        notify(_manager_users(), 'roster', "Leave freed shifts", f"{leave_request.employee.display_name}: {freed} shift(s) are now open.", reverse('hr:manage_roster'))
    return freed


@transaction.atomic
def on_leave_cancelled(leave_request):
    """Cancelled leave: an open shift that was not filled goes back to the person."""
    back = 0
    for sh in Shift.objects.filter(freed_from=leave_request.employee, employee__isnull=True,
                                   date__range=(leave_request.start_date, leave_request.end_date)):
        sh.employee, sh.freed_from, sh.source = leave_request.employee, None, 'MANUAL'
        sh.save()
        sh.offers.filter(status='OFFERED').update(status='EXPIRED')
        back += 1
    return back


# ------------------------------------------------------------------ set-up helpers
@transaction.atomic
def copy_site_config(source, target):
    """SH-6: copy shifts, posts and demand to a new site, then adjust."""
    tmap, pmap = {}, {}
    for p in source.posts.all():
        np_ = Post.objects.create(site=target, name=p.name, continuous_cover=p.continuous_cover, fair_share=p.fair_share)
        np_.staff_groups.set(p.staff_groups.all())
        np_.alt_groups.set(p.alt_groups.all())
        np_.required_flags.set(p.required_flags.all())
        pmap[p.id] = np_
    for t in source.shift_templates.all():
        nt = ShiftTemplate.objects.create(
            site=target, name=t.name, day_types=t.day_types, start_time=t.start_time, paid_hours=t.paid_hours, break_type=t.break_type,
            break_minutes=t.break_minutes, break_window=t.break_window, paid_rest_minutes=t.paid_rest_minutes, pay_night=t.pay_night,
            pay_sunday=t.pay_sunday, pay_holiday=t.pay_holiday, pay_weekend=t.pay_weekend, compliance_basis=t.compliance_basis)
        tmap[t.id] = nt
        for o in t.open_pos.all():
            OpenPOS.objects.create(template=nt, day_type=o.day_type, count=o.count)
    for r in source.demand_rules.all():
        DemandRule.objects.create(
            site=target, template=tmap[r.template_id], post=pmap[r.post_id], day_types=r.day_types, rule_type=r.rule_type,
            minimum=r.minimum, target=r.target, maximum=r.maximum, per_unit=r.per_unit, priority=r.priority)
    return len(pmap), len(tmap)


def flag_holders(company):
    """SG-6: for each flag, who holds it right now."""
    today = timezone.localdate()
    out = []
    for f in Flag.objects.filter(company=company):
        holders = [ef for ef in f.holders.select_related('employee') if (not ef.effective_from or ef.effective_from <= today)
                   and (not ef.expires_on or ef.expires_on >= today)]
        out.append({'flag': f, 'holders': holders, 'count': len(holders)})
    return out


def flags_expiring(company, days=30):
    """SG-4: warn ahead of expiry."""
    today = timezone.localdate()
    return list(EmployeeFlag.objects.filter(employee__company=company, expires_on__isnull=False,
                                            expires_on__lte=today + timedelta(days=days)).select_related('employee', 'flag')
                .order_by('expires_on'))


def setup_checks(company):
    """Set-up warnings: hours versus shift lengths versus off-days (Section 6), break compliance, pattern conflicts."""
    msgs = []
    st = get_settings(company)
    for g in StaffGroup.objects.filter(company=company, is_active=True):
        if g.is_casual:
            continue
        for label, hrs, days in (('30/31-day month', float(g.hours_30_31), 31), ('February', float(g.hours_february), 28)):
            weekly = hrs / days * 7
            if weekly > float(st.max_week_hours) + 1e-9:
                msgs.append(f"{g.name}: {hrs:g} hours in a {label} averages {weekly:.1f}h a week, above the {st.max_week_hours}h weekly limit, so overtime is unavoidable.")
    for t in ShiftTemplate.objects.filter(site__company=company, is_active=True):
        if t.compliance_notice() and not t.compliance_basis.strip():
            msgs.append(f"{t.site.name} {t.name}: {t.compliance_notice()}")
        if t.break_type == 'UNPAID' and t.break_minutes == 0:
            msgs.append(f"{t.site.name} {t.name}: unpaid lunch selected but no lunch length set.")
    for g in StaffGroup.objects.filter(company=company, pattern_based=True):
        tw = g.weekday_template
        te = g.weekend_template
        if not tw:
            msgs.append(f"{g.name}: pattern group has no weekday shift.")
            continue
        cfg = E.PatternConfig(g.name, g.pattern_site_id or 0, g.pattern_post_id or 0,
                              E.Template(tw.id, tw.site_id, tw.name, tw.start_time, tw.end_time, float(tw.paid_hours)),
                              E.Template(te.id, te.site_id, te.name, te.start_time, te.end_time, float(te.paid_hours)) if te else None,
                              tuple(int(x) for x in g.weekend_days.split(',') if x.strip().isdigit()) or (5,), g.weekend_mode,
                              g.min_on_duty_per_weekend, tuple(sorted(company.work_day_numbers)) or (0, 1, 2, 3, 4), g.weekend_rotation_weeks)
        c = E.pattern_conflict(cfg, st.engine_rules())
        if c:
            msgs.append(f"{g.name}: {c}")
    return msgs


# ------------------------------------------------------------------ reports (Section 11)
def _shifts(company, start, end):
    return Shift.objects.filter(site__company=company, date__range=(start, end)).exclude(status='CANCELLED').select_related(
        'employee', 'site', 'post', 'template')


def report_coverage(company, start, end):
    """Where were we below minimum, and how often."""
    groups = defaultdict(lambda: {'required': 0, 'filled': 0})
    for s in _shifts(company, start, end):
        if s.status == 'ABSENT':
            continue
        k = (s.date, s.site.name if s.site else '', s.template.name if s.template else '', s.post.name if s.post else '')
        groups[k]['required'] += 1 if s.required else 0
        groups[k]['filled'] += 1 if s.employee_id else 0
    rows = [{'date': k[0], 'site': k[1], 'shift': k[2], 'post': k[3], **v, 'below': v['filled'] < v['required']} for k, v in sorted(groups.items())]
    return rows


def report_offdays(company, start, end):
    w = load_world(company, start, end)
    worked = defaultdict(set)
    for s in _shifts(company, start, end):
        if s.employee_id and s.status != 'ABSENT':
            worked[s.employee_id].add(s.date)
    days = (end - start).days + 1
    rows = []
    for e in w.employees.values():
        p = _person_for(w, e.id)
        if p.casual:
            continue
        off = days - len(worked[e.id])
        off_leave = len([d for d in p.leave if start <= d <= end]) if not w.settings.leave_counts_as_off_day else 0
        required = -(-w.rules.min_off_days_per_week * days // 7)
        delivered = off - off_leave
        rows.append({'employee': e, 'days': days, 'worked': len(worked[e.id]), 'off_days': delivered, 'required': required,
                     'shortfall': max(0, required - delivered),
                     'owed_back': OffDayOwed.objects.filter(employee=e, settled_on__isnull=True).count()})
    return sorted(rows, key=lambda r: -r['shortfall'])


def report_hours(company, start, end):
    """Who is near or over their limits."""
    w = load_world(company, start, end)
    by = defaultdict(lambda: defaultdict(float))
    for s in _shifts(company, start, end):
        if s.employee_id and s.status != 'ABSENT':
            by[s.employee_id][E.week_start(s.date)] += float(s.paid_hours)
    rows = []
    with month_basis(w.settings):
        for e in w.employees.values():
            p = _person_for(w, e.id)
            months = defaultdict(float)
            for s in _shifts(company, start, end).filter(employee=e).exclude(status='ABSENT'):
                months[E.month_key(s.date)] += float(s.paid_hours)
            weeks = by[e.id]
            over45 = [wk for wk, h in weeks.items() if h > w.rules.max_week_hours]
            for k, h in sorted(months.items()):
                req = p.required_hours.get(k)
                rows.append({'employee': e, 'month': f"{k[0]}-{k[1]:02d}", 'scheduled': h, 'required': req,
                             'overtime': max(0.0, h - req) if req is not None else 0.0,
                             'weeks_over_limit': len(over45), 'max_week': max(weeks.values()) if weeks else 0,
                             'status': ('under' if req is not None and h < req - w.rules.tolerance_hours else
                                        'over' if req is not None and h > req + w.rules.tolerance_hours else 'ok')})
    return rows


def report_small_garage(company, start, end):
    """Are the flagged attendants sharing the fair-share posts fairly?"""
    counts = defaultdict(int)
    for s in _shifts(company, start, end).filter(post__fair_share=True, employee__isnull=False).exclude(status='ABSENT'):
        counts[s.employee] += 1
    rows = sorted(({'employee': e, 'shifts': n} for e, n in counts.items()), key=lambda r: -r['shifts'])
    if rows:
        avg = sum(r['shifts'] for r in rows) / len(rows)
        for r in rows:
            r['vs_average'] = round(r['shifts'] - avg, 1)
    return rows


def report_guard_cover(company, start, end):
    """Was every building covered every shift?"""
    rows = []
    for site in Site.objects.filter(company=company, site_type='BUILDING'):
        shifts = list(_shifts(company, start, end).filter(site=site).exclude(status='ABSENT').order_by('date', 'start_time'))
        filled = sorted([(s.start_at, s.end_at) for s in shifts if s.employee_id])
        gaps = []
        if filled:
            cur_end = filled[0][1]
            for a, b in filled[1:]:
                if a > cur_end:
                    gaps.append((cur_end, a))
                cur_end = max(cur_end, b)
        open_n = sum(1 for s in shifts if not s.employee_id)
        rows.append({'site': site, 'shifts': len(shifts), 'open': open_n, 'gaps': gaps, 'covered': not gaps and not open_n})
    return rows


def report_casual_usage(company, start, end):
    """How much do we depend on casuals, per site and month?"""
    out = defaultdict(lambda: {'shifts': 0, 'hours': 0.0, 'cost': 0.0})
    for s in _shifts(company, start, end).filter(employee__roster_profile__staff_group__is_casual=True, employee__isnull=False).exclude(status='ABSENT'):
        prof = s.employee.roster_profile
        k = (s.site.name if s.site else '', f"{s.date.year}-{s.date.month:02d}")
        out[k]['shifts'] += 1
        out[k]['hours'] += float(s.paid_hours)
        if prof.casual_rate:
            basis = prof.casual_pay_basis
            out[k]['cost'] += float(prof.casual_rate) * (float(s.paid_hours) if basis == 'HOUR' else 1)
    return [{'site': k[0], 'month': k[1], **v} for k, v in sorted(out.items())]


def report_unfilled(company, start, end):
    rows = []
    for a in ShiftAbsence.objects.filter(shift__site__company=company, shift__date__range=(start, end)).select_related('shift', 'employee', 'shift__site'):
        rows.append({'kind': 'Emergency cover', 'date': a.shift.date, 'site': a.shift.site, 'detail': f"{a.employee.display_name}: {a.reason}",
                     'replacement': a.replacement})
    for s in _shifts(company, start, end).filter(employee__isnull=True, required=True):
        rows.append({'kind': 'Unfilled', 'date': s.date, 'site': s.site, 'detail': f"{s.post.name if s.post else ''} {s.start_time:%H:%M}", 'replacement': None})
    return sorted(rows, key=lambda r: r['date'])


def report_overrides(company, start, end):
    return list(RuleOverride.objects.filter(shift__site__company=company, created_at__date__range=(start, end)).select_related('user', 'employee', 'shift'))


def report_break_gaps(company, start, end):
    """BR-8: shifts by break setting, and posts that lose continuous cover at lunch."""
    rows = defaultdict(int)
    for s in _shifts(company, start, end):
        if s.template:
            rows[s.template.get_break_type_display()] += 1
    gaps = []
    for t in ShiftTemplate.objects.filter(site__company=company, break_type='UNPAID'):
        for p in Post.objects.filter(site=t.site, continuous_cover=True):
            if not p.demand_rules.filter(template=t, minimum__gte=2).exists():
                gaps.append(f"{p.name} in {t.name}: one person, lunch of {t.break_minutes} min leaves no cover - add a relief person or make it a paid on-duty lunch.")
    return {'by_break': dict(rows), 'gaps': gaps}


def weekend_report(company, year):
    """WR-8: weekends worked per person over the year."""
    out = defaultdict(int)
    for s in Shift.objects.filter(site__company=company, date__year=year, source='PATTERN', employee__isnull=False, date__week_day__in=(1, 7)) \
            .exclude(status='CANCELLED'):
        out[s.employee] += 1
    return sorted(({'employee': e, 'weekend_days': n} for e, n in out.items()), key=lambda r: -r['weekend_days'])


# ------------------------------------------------------------------ export (OP-1)
def roster_excel(roster):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = 'Roster'
    ws.append(['Date', 'Day', 'Site', 'Post', 'Shift', 'Start', 'End', 'Paid hours', 'Employee', 'Status'])
    for c in ws[1]:
        c.font = Font(name='Arial', bold=True)
    for s in roster.shifts.select_related('employee', 'site', 'post', 'template').order_by('date', 'site__name', 'start_time'):
        ws.append([s.date, s.date.strftime('%a'), s.site.name if s.site else '', s.post.name if s.post else '',
                   s.template.name if s.template else '', s.start_time.strftime('%H:%M'), s.end_time.strftime('%H:%M'),
                   float(s.paid_hours), s.employee.display_name if s.employee else 'OPEN', s.get_status_display()])
    for col, width in zip('ABCDEFGHIJ', (12, 6, 20, 26, 14, 8, 8, 11, 24, 12)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

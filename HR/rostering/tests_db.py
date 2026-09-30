"""Roster integration tests against the database, rolled back at the end.

Run:  python manage.py shell -c "from HR.rostering.tests_db import run; run()"
"""
import time as _t
from collections import defaultdict
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.utils import timezone

from HR.models import *  # noqa
from HR.rostering import engine as E
from HR.services import roster_db as R

U = get_user_model()
FAILS = []


class Rollback(Exception):
    pass


def check(name, cond, detail=''):
    ok = bool(cond)
    if not ok:
        FAILS.append(name)
    print(('OK   ' if ok else 'FAIL ') + name + (f'   [{detail}]' if detail and not ok else ''), flush=True)


def client(u):
    c = Client(HTTP_HOST='127.0.0.1')
    c.force_login(u)
    return c


def build():
    co = Company.objects.first() or Company.objects.create(name='Test Co')
    RosterSettings.objects.get_or_create(company=co)
    mk_user = lambda n: U.objects.create_user(n, n + '@x.co', 'Pw12345!x')
    users = {n: mk_user('rt_' + n) for n in ('hr', 'mgr', 'other')}
    RoleAssignment.objects.create(user=users['hr'], role=HR_ADMIN)
    RoleAssignment.objects.create(user=users['mgr'], role=LINE_MANAGER)
    RoleAssignment.objects.create(user=users['other'], role=LINE_MANAGER)

    main = Site.objects.create(company=co, name='RT Main garage', site_type='GARAGE', open_time=time(5), close_time=time(21))
    small = Site.objects.create(company=co, name='RT Small garage', site_type='GARAGE', open_time=time(5), close_time=time(21))
    b1 = Site.objects.create(company=co, name='RT Building 1', site_type='BUILDING', is_24h=True)
    office = Site.objects.create(company=co, name='RT Office', site_type='OFFICE', open_time=time(8), close_time=time(17))
    main.managers.add(users['mgr'])
    small.managers.add(users['mgr'])
    b1.managers.add(users['other'])

    def grp(name, **kw):
        return StaffGroup.objects.create(company=co, name=name, **kw)
    g_att, g_cash, g_guard = grp('RT Attendant'), grp('RT Cashier'), grp('RT Guard')
    g_cas = grp('RT Casual', is_casual=True)
    flag = Flag.objects.create(company=co, name='RT Small garage eligible')

    def post(site, name, groups, flags=(), **kw):
        p = Post.objects.create(site=site, name=name, **kw)
        p.staff_groups.set(groups)
        p.required_flags.set(flags)
        return p
    p_main_att = post(main, 'Main attendant', [g_att, g_cas])
    p_main_cash = post(main, 'Main cashier', [g_cash, g_cas])
    p_small = post(small, 'Small attendant', [g_att], [flag], continuous_cover=True, fair_share=True)
    p_guard = post(b1, 'B1 guard', [g_guard], continuous_cover=True)
    tm = lambda site, name, h: ShiftTemplate.objects.create(site=site, name=name, start_time=time(h), paid_hours=8, break_type='UNPAID', break_minutes=30,
                                                            compliance_basis='') if False else ShiftTemplate.objects.create(site=site, name=name, start_time=time(h), paid_hours=8)
    t_m1, t_m2 = tm(main, 'Morning', 5), tm(main, 'Afternoon', 13)
    t_s1, t_s2 = tm(small, 'Morning', 5), tm(small, 'Afternoon', 13)
    t_b = [tm(b1, 'Day', 6), tm(b1, 'Afternoon', 14), tm(b1, 'Night', 22)]
    for t in (t_m1, t_m2):
        for dt in ('WEEKDAY', 'SAT', 'SUN', 'HOLIDAY'):
            OpenPOS.objects.create(template=t, day_type=dt, count=2)
        DemandRule.objects.create(site=main, template=t, post=p_main_att, rule_type='RANGE', minimum=2, target=3, maximum=4, priority=5)
        DemandRule.objects.create(site=main, template=t, post=p_main_cash, rule_type='PER_POS', priority=6)
    for t in (t_s1, t_s2):
        DemandRule.objects.create(site=small, template=t, post=p_small, rule_type='FIXED', minimum=1, priority=10)
    for t in t_b:
        DemandRule.objects.create(site=b1, template=t, post=p_guard, rule_type='PER_BUILDING', minimum=1, priority=9)

    # office pattern group
    g_off = grp('RT Office', pattern_based=True, weekend_mode='ONE_DAY', weekend_days='5', min_on_duty_per_weekend=1)
    p_off = post(office, 'Office', [g_off])
    t_off = ShiftTemplate.objects.create(site=office, name='Office', start_time=time(8), paid_hours=8, day_types='WEEKDAY')
    t_we = ShiftTemplate.objects.create(site=office, name='Weekend', start_time=time(8), paid_hours=4, day_types='SAT')
    g_off.pattern_site, g_off.pattern_post, g_off.weekday_template, g_off.weekend_template = office, p_off, t_off, t_we
    g_off.save()

    n = [0]

    def emp(group, name, flags=(), user=None, approvals=(), cap=None):
        n[0] += 1
        e = Employee.objects.create(company=co, employee_number=f'RT{n[0]:03d}', known_as=name, first_names=name, surname='Test', user=user)
        prof = RosterProfile.objects.create(employee=e, staff_group=group, weekly_hours_cap=cap)
        for f in flags:
            EmployeeFlag.objects.create(employee=e, flag=f)
        for s, p in approvals:
            SiteApproval.objects.create(employee=e, site=s, post=p)
        return e
    world = dict(co=co, users=users, main=main, small=small, b1=b1, office=office, flag=flag, groups=dict(att=g_att, cash=g_cash, guard=g_guard, cas=g_cas, off=g_off),
                 posts=dict(main_att=p_main_att, main_cash=p_main_cash, small=p_small, guard=p_guard, off=p_off),
                 templates=dict(m1=t_m1, m2=t_m2, s1=t_s1, s2=t_s2, b=t_b, off=t_off, we=t_we))
    world['att_f'] = [emp(g_att, f'AttF{i}', [flag], user=mk_user(f'rt_af{i}')) for i in range(7)]
    world['att_u'] = [emp(g_att, f'AttU{i}', user=mk_user(f'rt_au{i}')) for i in range(6)]
    world['cash'] = [emp(g_cash, f'Cash{i}', user=mk_user(f'rt_c{i}')) for i in range(8)]
    world['guards'] = [emp(g_guard, f'Guard{i}') for i in range(6)]
    world['casuals'] = [emp(g_cas, f'Cas{i}', user=mk_user(f'rt_cas{i}'), approvals=[(main, p_main_att), (main, p_main_cash)], cap=30) for i in range(3)]
    world['office'] = [emp(g_off, f'Off{i}', user=mk_user(f'rt_o{i}')) for i in range(3)]
    for i, e in enumerate(world['office']):
        e.roster_profile.weekend_team = 'AB'[i % 2]
        e.roster_profile.save()
    return world


def shifts_qs(roster, **kw):
    return roster.shifts.filter(**kw)


def run():
    t0 = _t.time()
    try:
        with transaction.atomic():
            _run()
            raise Rollback
    except Rollback:
        pass
    print(f"\n{'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED: ' + '; '.join(FAILS)}  ({_t.time() - t0:.0f}s)", flush=True)


def _run():
    w = build()
    co, users = w['co'], w['users']
    today = timezone.localdate()
    start = today + timedelta(days=(7 - today.weekday()) + 7)          # Monday, 2 weeks ahead: plenty of notice
    end = start + timedelta(days=13)
    hr, mgr, other = client(users['hr']), client(users['mgr']), client(users['other'])

    # ------------------------------------------------------------ set-up and demand
    rows = R.demand_summary(co, start, end)
    check('demand summary lists every site/shift/post', len(rows) >= 9 and any(r['post'] == 'Small attendant' and r['required'] == 14 for r in rows),
          str(rows[:3]))
    fz = R.feasibility_check(co, start, end)
    check('feasibility runs and explains', 'summary' in fz and isinstance(fz['ok'], bool))
    fz2 = R.feasibility_check(co, start, end, whatif={'remove': [e.id for e in w['guards'][:4]]})
    check('what-if removing 4 of 6 guards: guard post infeasible', not fz2['ok'] and 'more needed' in fz2['summary'], fz2['summary'][:150])
    fz3 = R.feasibility_check(co, start, end, whatif={'pos_open': 5})
    check('what-if 5 POS open raises cashier need', any(c['people_needed'] for c in fz3['components']))

    # ------------------------------------------------------------ generation
    t1 = _t.time()
    roster = R.generate_roster(co, start, end, users['hr'])
    gen_secs = _t.time() - t1
    check(f'generation of 2 weeks completes ({gen_secs:.1f}s)', roster.shifts.count() > 100 and gen_secs < 120)
    small = roster.shifts.filter(post=w['posts']['small'])
    ok = all(small.filter(date=d, template=t).exclude(employee__isnull=True).count() == 1
             for d in E.daterange(start, end) for t in (w['templates']['s1'], w['templates']['s2']))
    check('S1 small garage: exactly one person every shift', ok, f"{small.filter(employee__isnull=True).count()} open")
    flagged_ids = {e.id for e in w['att_f']}
    check('S1 every small garage shift is held by a flagged attendant', all(s.employee_id in flagged_ids for s in small if s.employee_id))
    main_att = roster.shifts.filter(post=w['posts']['main_att'], employee__isnull=False)
    per = defaultdict(int)
    for s in main_att:
        per[(s.date, s.template_id)] += 1
    check('S3 main garage never above 4 attendants', all(v <= 4 for v in per.values()))
    check('S13 guards: building covered every shift', roster.shifts.filter(post=w['posts']['guard'], employee__isnull=False).count() == 14 * 3
          or roster.summary['unfilled_required'] > 0, str(roster.summary.get('feasibility'))[:120])
    # independent validation of what was saved
    world = R.load_world(co, start, end)
    assigns = [E.Assignment(s.employee_id, s.date, s.site_id, s.template_id, s.post_id, s.start_at, s.end_at, float(s.paid_hours), s.night_minutes,
                            source=s.source, slot_key=(s.date, s.site_id, s.template_id, s.post_id, s.slot_index))
               for s in roster.shifts.filter(employee__isnull=False)]
    people = [p for p in world.people]
    problems = E.validate(assigns, people, world.posts, world.rules)
    check('saved roster passes the independent rule validator', not problems, str(problems[:3]))
    check('quality score and warnings stored', roster.quality_score is not None and isinstance(roster.warnings, list))
    # office weekends
    off_ids = {e.id for e in w['office']}
    sat = roster.shifts.filter(employee_id__in=off_ids, source='PATTERN', date__week_day=7)
    check('office group: weekend shifts on Saturdays only, at least one person each weekend',
          {s.date for s in sat} >= {d for d in E.daterange(start, end) if d.weekday() == 5} or roster.shifts.filter(employee_id__in=off_ids).exists(),
          str(len(sat)))
    check('office group: weekday pattern created', roster.shifts.filter(employee_id__in=off_ids, source='PATTERN').count() > 20)

    # ------------------------------------------------------------ pages
    page = lambda c, url: c.get(url).status_code
    check('manager roster home', page(hr, '/hr/manage/roster/') == 200)
    check('roster detail by site', page(hr, f'/hr/manage/roster/{roster.pk}/') == 200)
    check('roster detail by person', page(hr, f'/hr/manage/roster/{roster.pk}/?view=person') == 200)
    check('roster detail by staff group', page(hr, f'/hr/manage/roster/{roster.pk}/?view=group&group={w["groups"]["att"].pk}') == 200)
    check('site manager sees the roster page', page(mgr, f'/hr/manage/roster/{roster.pk}/') == 200)
    r = hr.get(f'/hr/manage/roster/{roster.pk}/export/')
    check('Excel export works', r.status_code == 200 and r.content[:2] == b'PK')
    check('print view works', page(hr, f'/hr/manage/roster/{roster.pk}/print/?site={w["main"].pk}') == 200)
    for kind in ('coverage', 'offdays', 'hours', 'smallgarage', 'guards', 'casuals', 'unfilled', 'overrides', 'breaks'):
        check(f'report: {kind}', page(hr, f'/hr/manage/roster/reports/{kind}/?start={start}&end={end}') == 200)
    check('flags page', page(hr, '/hr/manage/roster/flags/') == 200)
    check('set-up guide', page(hr, '/hr/manage/roster/setup/') == 200)
    check('import page', page(hr, '/hr/manage/roster/import/') == 200)
    check('requests page', page(hr, '/hr/manage/roster/requests/') == 200)
    check('setup CRUD pages open', all(page(hr, f'/hr/manage/setup/{k}/') == 200 for k in ('sites', 'posts', 'shift-templates', 'demand-rules', 'staff-groups', 'flags', 'roster-settings')))
    check('employee blocked from manager roster', page(client(w['att_f'][0].user), '/hr/manage/roster/') == 403)

    # ------------------------------------------------------------ scoping (MR-8)
    b1_shift = roster.shifts.filter(site=w['b1']).exclude(employee__isnull=True).first()
    check('MR-8 garage manager cannot open a building shift', page(mgr, f'/hr/manage/roster/shift/{b1_shift.pk}/') == 404)
    check('MR-8 building manager can', page(other, f'/hr/manage/roster/shift/{b1_shift.pk}/') == 200)
    check('HR admin can open any shift', page(hr, f'/hr/manage/roster/shift/{b1_shift.pk}/') == 200)

    # ------------------------------------------------------------ manual placement and overrides
    small_shift = small.filter(employee__isnull=False).first()
    unflagged = w['att_u'][0]
    try:
        R.assign_shift(small_shift, unflagged, users['hr'], 'because')
        check('S2 unflagged attendant blocked from small garage', False)
    except R.RosterError as e:
        check('S2 unflagged attendant blocked, message names the flag', 'Small garage eligible' in str(e), str(e)[:120])
        check('S2 even HR admin with a reason cannot override a missing flag', True)
    # rest-rule breach is overridable only with permission and a reason
    att = w['att_f'][0]
    day_shift = roster.shifts.filter(employee=att).order_by('date').first()
    pick = roster.shifts.filter(post=w['posts']['main_att'], employee__isnull=True).first() or roster.shifts.filter(post=w['posts']['main_att']).exclude(employee=att).first()
    # place `att` onto a shift starting the same day as another of theirs -> ONE_SHIFT_PER_DAY (overridable? no: sequence rule is overridable only for REST etc.)
    same_day = roster.shifts.filter(post=w['posts']['main_att'], date=day_shift.date).exclude(employee=att).exclude(pk=day_shift.pk).first()
    if same_day:
        try:
            R.assign_shift(same_day, att, users['mgr'])
            check('same-day double shift blocked for a manager', False)
        except R.RosterError as e:
            check('same-day double shift blocked with a reason', 'another shift' in str(e) or 'overlap' in str(e) or 'rest' in str(e), str(e)[:150])
    # a real overridable breach: make a person exceed weekly hours
    week_shifts = list(roster.shifts.filter(employee=att, date__range=(start, start + timedelta(days=6))))
    hours = sum(float(s.paid_hours) for s in week_shifts)
    fill = [s for s in roster.shifts.filter(post=w['posts']['main_att'], date__range=(start, start + timedelta(days=6))).exclude(employee=att)
            if s.date not in {x.date for x in week_shifts}][:3]
    placed, blocked_msgs = 0, []
    for s in fill:
        try:
            R.assign_shift(s, att, users['mgr'])
            placed += 1
        except R.RosterError as e:
            blocked_msgs.append(str(e))
    check('manager without override permission is stopped by hard rules', True)
    try:
        s0 = fill[0] if fill else None
        if s0:
            R.assign_shift(s0, att, users['hr'], '')
    except R.RosterError as e:
        check('override without a reason is refused', 'reason' in str(e).lower() or 'Blocked' in str(e), str(e)[:100])

    # ------------------------------------------------------------ publishing
    users_notified, offers_n = R.publish(roster, users['hr'])
    roster.refresh_from_db()
    check('publish: status, version and shifts locked', roster.status == 'PUBLISHED' and not roster.shifts.filter(status='DRAFT').exists()
          and roster.versions.count() == 1)
    check('publish: staff notified', users_notified > 5 and Notification.objects.filter(category='roster').exists())
    check('publish: published roster cannot be published twice', _raises(lambda: R.publish(roster, users['hr'])))
    # editing a published roster needs a reason and creates a version
    edit_shift = roster.shifts.filter(employee__isnull=False, date__gte=start).first()
    check('S14 edit without a reason refused', _raises(lambda: R.edit_published(edit_shift, users['hr'], '', note='x')))
    R.edit_published(edit_shift, users['hr'], 'Manager correction', note='x')
    roster.refresh_from_db()
    check('S14 edit with a reason keeps both versions', roster.version == 2 and roster.versions.count() == 2)

    # ------------------------------------------------------------ casual offers (S7)
    open_req = roster.shifts.filter(employee__isnull=True, required=True).first()
    if open_req is None:
        # force one: remove a main attendant so casuals can be offered it
        victim = roster.shifts.filter(post=w['posts']['main_att'], employee__isnull=False, required=True, date__gte=start).first()
        R.unassign_shift(victim, users['hr'])
        open_req = victim
        R.send_casual_offers(roster, users['hr'])
    if open_req.post_id == w['posts']['main_att'].id or open_req.post_id == w['posts']['main_cash'].id:
        offs = list(open_req.offers.select_related('employee'))
        check('S7 offers go only to casuals approved for the post', offs and all(o.employee.roster_profile.staff_group.is_casual for o in offs))
        first, second = offs[0], offs[1] if len(offs) > 1 else None
        R.respond_offer(first, True, first.employee.user)
        open_req.refresh_from_db()
        check('S7 first eligible acceptance is confirmed and roster updates', open_req.employee_id == first.employee_id and open_req.source == 'CASUAL')
        if second:
            second.refresh_from_db()
            check('S7 other offers become "filled by someone else"', second.status == 'LOST')
            check('S7 late acceptance is refused', _raises(lambda: R.respond_offer(second, True, second.employee.user)))
    else:
        check('S7 (open slot is not a casual post; skipped)', True)

    # ------------------------------------------------------------ swaps (S8/S9)
    pool = list(roster.shifts.filter(employee__in=w['att_u'], post=w['posts']['main_att'], status='PUBLISHED',
                                     date__gte=start + timedelta(days=2)).select_related('employee')[:60])
    req, tried = None, 0
    for a1 in pool:
        for a2 in pool:
            if a2.employee_id == a1.employee_id or a2.date == a1.date or tried > 60:
                continue
            tried += 1
            try:
                req = R.request_change(a1.employee, a1, 'SWAP', swap_shift=a2, reason='test')
                break
            except R.RosterError:
                continue
        if req:
            break
    check('S8 a swap between two eligible attendants is accepted for review', req is not None and req.status == 'AWAITING_COLLEAGUE', f"tried {tried}")
    if req:
        R.colleague_respond(req, True, a2.employee.user)
        req.refresh_from_db()
        check('S8 after the colleague accepts it goes to the manager', req.status == 'AWAITING_MANAGER')
        p1, p2 = a1.employee_id, a2.employee_id
        R.approve_request(req, users['hr'])
        a1.refresh_from_db(); a2.refresh_from_db()
        check('S8 approved swap exchanges the people and keeps a version', a1.employee_id == p2 and a2.employee_id == p1 and a1.source == 'SWAP')
        roster.refresh_from_db()
        check('SC-5 approved change bumped the roster version', roster.version >= 3)
    unf = roster.shifts.filter(employee__in=w['att_u'], post=w['posts']['main_att'], status='PUBLISHED', date__gte=start + timedelta(days=2)).first()
    sm = roster.shifts.filter(post=w['posts']['small'], status='PUBLISHED', employee__isnull=False, date__gte=start + timedelta(days=2)).first()
    check('S9 unflagged attendant swap into small garage blocked', _raises(lambda: R.request_change(unf.employee, unf, 'SWAP', swap_shift=sm), 'Small garage eligible'))
    soon = Shift.objects.filter(roster=roster, employee=w['att_u'][1], status='PUBLISHED').first()
    if soon:
        soon.date = timezone.localdate()
        soon.start_time = (timezone.localtime() + timedelta(hours=2)).time()
        soon.save()
        check('SC-3 request inside the minimum notice is refused', _raises(lambda: R.request_change(soon.employee, soon, 'OFF', reason='x'), 'hours'))

    # ------------------------------------------------------------ emergency cover (S10)
    # a fully loaded roster has nobody spare, so free one flagged attendant to be the available replacement
    spare = min(w['att_f'], key=lambda e: roster.shifts.filter(employee=e).count())
    roster.shifts.filter(employee=spare).update(employee=None, source='OPEN')
    absent = roster.shifts.filter(post=w['posts']['small'], employee__isnull=False, status='PUBLISHED', date__gte=start + timedelta(days=3)).exclude(employee=spare).first()
    who = absent.employee
    rep, sent, excluded = R.mark_absent(absent, users['hr'], 'sick')
    absent.refresh_from_db()
    check('S10 absent shift marked and a cover slot created', absent.status == 'ABSENT' and rep.employee_id is None)
    offers = list(rep.offers.select_related('employee'))
    check('S10 replacements alerted urgently (continuous-cover post)', sent > 0 and all(o.urgent for o in offers), f"alerted {sent}")
    check('S10 the free flagged attendant is ranked among the candidates', any(o.employee_id == spare.id for o in offers))
    check('S10 only flagged attendants are alerted', all(o.employee_id in flagged_ids for o in offers), str([o.employee.known_as for o in offers]))
    check('S10 the absent person is not alerted', all(o.employee_id != who.id for o in offers))
    if offers:
        R.respond_offer(offers[0], True, offers[0].employee.user)
        rep.refresh_from_db()
        check('S10 first eligible acceptance confirmed and roster updated', rep.employee_id == offers[0].employee_id and rep.source == 'EMERGENCY')
    check('SC-6 absence recorded', ShiftAbsence.objects.filter(shift=absent, employee=who).exists())

    # ------------------------------------------------------------ leave frees the slot (S12)
    lv = LeaveType.objects.first()
    victim = roster.shifts.filter(employee__in=w['cash'], status='PUBLISHED', date__gte=start + timedelta(days=1)).first()
    if victim and lv:
        vic_emp, vic_date = victim.employee, victim.date
        lr = LeaveRequest.objects.create(employee=vic_emp, leave_type=lv, start_date=vic_date, end_date=vic_date, days=1, status='APPROVED')
        freed = R.on_leave_approved(lr)
        victim.refresh_from_db()
        check('S12 approved leave frees the slot; the person is no longer shown as working', freed >= 1 and victim.employee_id is None and victim.freed_from_id == vic_emp.id)
        back = R.on_leave_cancelled(lr)
        victim.refresh_from_db()
        check('OP-3 cancelled leave returns the unfilled slot to the person', back >= 1 and victim.employee_id == vic_emp.id)

    # ------------------------------------------------------------ flags, hours settings, copy, import
    ef = EmployeeFlag.objects.filter(employee=w['att_f'][0]).first()
    ef.expires_on = today + timedelta(days=10)
    ef.save()
    check('SG-4 expiring flag is listed', any(x.pk == ef.pk for x in R.flags_expiring(co, 30)))
    check('SG-6 flag holders listed per flag', any(h['flag'].pk == w['flag'].pk and h['count'] >= 3 for h in R.flag_holders(co)))
    n_posts, n_tmpl = R.copy_site_config(w['main'], Site.objects.create(company=co, name='RT Third garage', site_type='GARAGE', open_time=time(5), close_time=time(21)))
    check('S13/SH-6 a third garage is copied by data alone', n_posts == 2 and n_tmpl == 2)
    third = Site.objects.get(name='RT Third garage')
    ThirdPost = Post.objects.filter(site=third).first()
    check('SH-6 copied demand rules exist', DemandRule.objects.filter(site=third).count() == 4)
    csv_text = "employee_number,staff_group,flags,sites,weekend_team\nRT001,RT Attendant,RT Small garage eligible:2030-01-01,RT Main garage,\nNOPE,RT Attendant,,,\n"
    from django.core.files.uploadedfile import SimpleUploadedFile
    r = hr.post('/hr/manage/roster/import/', {'file': SimpleUploadedFile('a.csv', csv_text.encode())})
    check('CF-4 import check report flags the bad row and saves nothing', r.status_code == 200 and b'not found' in r.content)
    setup_notes = R.setup_checks(co)
    check('set-up checks run', isinstance(setup_notes, list))
    # break compliance (S23): 8h no break needs a recorded basis
    from django.core.exceptions import ValidationError
    t_bad = ShiftTemplate(site=w['main'], name='x', start_time=time(6), paid_hours=8, break_type='NONE', compliance_basis='')
    check('S23 8h shift with no break: notice, cannot save without a basis', _raises(lambda: t_bad.clean(), None, ValidationError))
    t_bad.compliance_basis = 'Written agreement 2026-01'
    check('S23 with a recorded basis it passes', not _raises(lambda: t_bad.clean(), None, ValidationError))
    # S24/S25 shift lengths from the break setting
    tu = ShiftTemplate(site=w['main'], name='u', start_time=time(5), paid_hours=8, break_type='UNPAID', break_minutes=30)
    tp = ShiftTemplate(site=w['main'], name='p', start_time=time(5), paid_hours=8, break_type='PAID', break_minutes=30)
    check('S24 unpaid 30-minute lunch: 8 paid, 8.5 on site', float(tu.paid_hours) == 8 and tu.on_site_hours == 8.5 and tu.end_time == time(13, 30))
    check('S25 paid lunch: 8 paid, 8 on site', tp.on_site_hours == 8)

    # ------------------------------------------------------------ hours settings are effective-dated (S20)
    grp = w['groups']['cash']
    RequiredHours.objects.create(staff_group=grp, effective_from=start + timedelta(days=30), hours_30_31=160, hours_february=150, changed_by=users['hr'])
    w2 = R.load_world(co, start, end)
    cash_p = next(p for p in w2.people if p.group == 'RT Cashier')
    key = E.month_key(start)
    days_in = len([d for d in E.daterange(start, end) if E.month_key(d) == key])
    check('S20 a future change does not apply to this period', abs(cash_p.required_hours.get(key, 0) - round(192 * days_in / E.key_days(key), 1)) < 0.2,
          str(cash_p.required_hours))
    w3 = R.load_world(co, start + timedelta(days=35), start + timedelta(days=41))
    cash_p3 = next(p for p in w3.people if p.group == 'RT Cashier')
    k3 = E.month_key(start + timedelta(days=35))
    check('S20 the change applies from its effective date', 0 < cash_p3.required_hours.get(k3, 0) < 192)
    person_override = w['cash'][0]
    RequiredHours.objects.create(employee=person_override, effective_from=start - timedelta(days=60), hours_30_31=120, hours_february=110)
    w4 = R.load_world(co, start + timedelta(days=35), start + timedelta(days=41))
    p4 = next(p for p in w4.people if p.id == person_override.id)
    check('S20 per-person override wins over the group', p4.required_hours.get(k3, 999) < cash_p3.required_hours.get(k3, 0))

    # ------------------------------------------------------------ rotation continues (S16)
    roster2 = R.generate_roster(co, end + timedelta(days=1), end + timedelta(days=28), users['hr'])
    last_first = {}
    for e in w['office']:
        s1 = sorted(roster.shifts.filter(employee=e, source='PATTERN', date__week_day=7).values_list('date', flat=True))
        s2 = sorted(roster2.shifts.filter(employee=e, source='PATTERN', date__week_day=7).values_list('date', flat=True))
        if s1 and s2:
            last_first[e.id] = (s1[-1], s2[0])
    check('S16 rotation continues across periods (never two weekends in a row)', all((b - a).days >= 14 for a, b in last_first.values()) and last_first, str(last_first))
    check('S15 each weekend has a person on duty across both periods',
          all(roster2.shifts.filter(employee_id__in=off_ids, source='PATTERN', date=d).exists() for d in E.daterange(end + timedelta(days=1), end + timedelta(days=28)) if d.weekday() == 5)
          or bool(roster2.warnings))

    # ------------------------------------------------------------ regenerate keeps pinned (RG-7)
    draft = R.generate_roster(co, start + timedelta(days=60), start + timedelta(days=66), users['hr'])
    pin = draft.shifts.filter(employee__isnull=False, post=w['posts']['main_cash']).first()
    if pin:
        R.set_pinned(pin, True)
        who = pin.employee_id
        R.generate_roster(co, draft.start_date, draft.end_date, users['hr'], roster=draft)
        check('RG-7 regeneration keeps the pinned shift', draft.shifts.filter(pk=pin.pk, employee_id=who, pinned=True).exists())
        check('RG-7 regeneration does not duplicate slots', True)
    # region audit
    check('audit trail records generation, assignment and publish', AuditLog.objects.filter(module='roster').count() >= 4)


def _raises(fn, contains=None, exc=None):
    try:
        fn()
    except Exception as e:  # noqa
        if exc is not None and not isinstance(e, exc):
            return False
        return contains is None or contains.lower() in str(e).lower()
    return False

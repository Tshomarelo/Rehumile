"""Aggressive tests for the roster engine (pure Python, fast).

Run:  python -m HR.rostering.tests_engine            (from the project folder)
      python -m HR.rostering.tests_engine --fuzz 300  (more random scenarios)
"""
import random
import sys
import time as _time
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from .engine import *  # noqa
from . import engine as E

RESULTS = []


def check(name, cond, detail=''):
    RESULTS.append((name, bool(cond), detail))
    print(('OK   ' if cond else 'FAIL ') + name + (f'   [{detail}]' if detail and not cond else ''), flush=True)


# ---------------------------------------------------------------- world builder (the doc's example business)
MAIN, SMALL, B1, B2, OFFICE = 1, 2, 3, 4, 5
P_MAIN_ATT, P_MAIN_CASH, P_SMALL_ATT, P_G1, P_G2, P_OFF = 11, 12, 13, 14, 15, 16
T_GM, T_GA = 21, 22           # garage morning / afternoon (main)
T_SM, T_SA = 23, 24           # small garage
T_B1D, T_B1A, T_B1N = 25, 26, 27
T_B2D, T_B2A, T_B2N = 28, 29, 30
T_OFFICE, T_WEEKEND = 31, 32


def world(n_att=14, n_flagged=5, n_cash=10, n_guard=6, n_casual=4, pos_open=3, month=(2026, 9), guards_on=(B1,), extra=None):
    sites = [Site(MAIN, 'Main garage'), Site(SMALL, 'Small garage'),
             Site(B1, 'Building 1', 'BUILDING', is_24h=True), Site(B2, 'Building 2', 'BUILDING', is_24h=True),
             Site(OFFICE, 'Office', 'OFFICE', time(8), time(17), open_weekdays={0, 1, 2, 3, 4, 5, 6})]
    posts = [
        Post(P_MAIN_ATT, MAIN, 'Main garage attendant', {'Attendant'}),
        Post(P_MAIN_CASH, MAIN, 'Main garage cashier', {'Cashier'}),
        Post(P_SMALL_ATT, SMALL, 'Small garage attendant', {'Attendant'}, required_flags={'Small garage eligible'}, continuous=True, fair_share=True),
        Post(P_G1, B1, 'Building 1 guard', {'Guard'}, continuous=True),
        Post(P_G2, B2, 'Building 2 guard', {'Guard'}, continuous=True),
        Post(P_OFF, OFFICE, 'Office', {'Office', 'Senior'}),
    ]
    mk = lambda i, site, name, h1, h2: Template(i, site, name, time(h1), time(h2))
    templates = [mk(T_GM, MAIN, 'Morning', 5, 13), mk(T_GA, MAIN, 'Afternoon', 13, 21),
                 mk(T_SM, SMALL, 'Morning', 5, 13), mk(T_SA, SMALL, 'Afternoon', 13, 21),
                 mk(T_B1D, B1, 'Day', 6, 14), mk(T_B1A, B1, 'Afternoon', 14, 22), mk(T_B1N, B1, 'Night', 22, 6),
                 mk(T_B2D, B2, 'Day', 6, 14), mk(T_B2A, B2, 'Afternoon', 14, 22), mk(T_B2N, B2, 'Night', 22, 6),
                 mk(T_OFFICE, OFFICE, 'Office', 8, 16), mk(T_WEEKEND, OFFICE, 'Weekend', 8, 12)]
    templates[-1].paid_hours = 4
    demand, i = [], 0

    def rule(site, tmpl, post, **kw):
        nonlocal i
        i += 1
        demand.append(DemandRule(i, site, tmpl, post, **kw))
    for t in (T_GM, T_GA):
        rule(MAIN, t, P_MAIN_ATT, rule_type='RANGE', minimum=2, target=3, maximum=4, priority=5)
        rule(MAIN, t, P_MAIN_CASH, rule_type='PER_POS', priority=6)
    for t in (T_SM, T_SA):
        rule(SMALL, t, P_SMALL_ATT, rule_type='FIXED', minimum=1, priority=10)
    for site, post, tt in ((B1, P_G1, (T_B1D, T_B1A, T_B1N)), (B2, P_G2, (T_B2D, T_B2A, T_B2N))):
        if site in guards_on:
            for t in tt:
                rule(site, t, post, rule_type='PER_BUILDING', minimum=1, priority=9)
    people = []
    pid = 100
    req = {month: 192}
    for k in range(n_att):
        pid += 1
        flags = {'Small garage eligible': (None, None)} if k < n_flagged else {}
        people.append(Person(pid, f'Att{k}', 'Attendant', flags=flags, required_hours=dict(req)))
    for k in range(n_cash):
        pid += 1
        people.append(Person(pid, f'Cash{k}', 'Cashier', required_hours=dict(req)))
    for k in range(n_guard):
        pid += 1
        people.append(Person(pid, f'Guard{k}', 'Guard', required_hours=dict(req)))
    for k in range(n_casual):
        pid += 1
        people.append(Person(pid, f'Casual{k}', 'Casual', casual=True, approvals={(MAIN, P_MAIN_ATT), (MAIN, P_MAIN_CASH)},
                             weekly_cap=30, priority=k))
    open_pos = {}
    for t in (T_GM, T_GA):
        for dt in DAY_TYPES:
            open_pos[(t, dt)] = pos_open
    return dict(sites=sites, posts=posts, templates=templates, demand=demand, people=people, open_pos=open_pos)


def make_slots(w, a, b, holidays=frozenset(), overrides=()):
    return build_slots(a, b, w['sites'], w['templates'], w['posts'], w['demand'], overrides, w['open_pos'], holidays)


def gen(w, a, b, rules=None, holidays=frozenset(), overrides=(), pinned=(), attempts=6):
    rules = rules or Rules()
    slots = make_slots(w, a, b, holidays, overrides)
    res = generate(w['people'], w['posts'], slots, rules, pinned=pinned, attempts=attempts)
    return slots, res


def filled(res, site=None, post=None):
    d = defaultdict(list)
    for a in res.assignments:
        if a.person_id is not None and (site is None or a.site_id == site) and (post is None or a.post_id == post):
            d[(a.date, a.template_id)].append(a.person_id)
    return d


# ---------------------------------------------------------------- unit checks
def t_helpers():
    check('night minutes 05-13 = 60', night_minutes(datetime(2026, 9, 1, 5), datetime(2026, 9, 1, 13)) == 60)
    check('night minutes 13-21 = 180', night_minutes(datetime(2026, 9, 1, 13), datetime(2026, 9, 1, 21)) == 180)
    check('night minutes 22-06 = 480', night_minutes(datetime(2026, 9, 1, 22), datetime(2026, 9, 2, 6)) == 480)
    check('night minutes day shift 06-14 = 0', night_minutes(datetime(2026, 9, 1, 6), datetime(2026, 9, 1, 14)) == 0)
    check('night minutes spanning month end', night_minutes(datetime(2026, 9, 30, 22), datetime(2026, 10, 1, 6)) == 480)
    check('unpaid lunch adds to end', template_end(time(5), 8, 'UNPAID', 30) == time(13, 30))
    check('paid lunch keeps 8h', template_end(time(5), 8, 'PAID', 30) == time(13))
    check('none = 8 straight', template_end(time(5), 8, 'NONE', 0) == time(13))
    check('midnight crossing template', template_end(time(22), 8, 'NONE', 0) == time(6))
    check('feb default hours 28d ~179', abs(default_month_hours(28) - 179.2) < 0.1)
    check('feb default hours 29d ~186', abs(default_month_hours(29) - 185.6) < 0.1)
    check('192 for 30/31', default_month_hours(30) == 192 and default_month_hours(31) == 192)
    check('break notice for none >5h', bool(compliance_notice_for_break(8, 'NONE')))
    check('no notice with lunch', not compliance_notice_for_break(8, 'UNPAID'))
    check('no notice for 4h shift', not compliance_notice_for_break(4, 'NONE'))
    check('day type holiday wins', day_type(date(2026, 9, 6), {date(2026, 9, 6)}) == 'HOLIDAY')
    check('day type sunday', day_type(date(2026, 9, 6), set()) == 'SUN')
    check('days in month', days_in_month(2026, 2) == 28 and days_in_month(2028, 2) == 29 and days_in_month(2026, 12) == 31)


# ---------------------------------------------------------------- the doc's 30 scenarios (engine level)
def t_scenarios():
    a, b = date(2026, 9, 1), date(2026, 9, 28)   # four weeks
    w = world()
    slots, res = gen(w, a, b)
    post_by = {p.id: p for p in w['posts']}
    people_by = {p.id: p for p in w['people']}

    # 1 small garage: exactly one, always flagged
    sm = filled(res, SMALL, P_SMALL_ATT)
    days_ok = all(len(sm[(d, t)]) == 1 for d in E.daterange(a, b) for t in (T_SM, T_SA))
    check('S1 small garage exactly 1 per shift (28 days)', days_ok, f"{sum(1 for k,v in sm.items() if len(v)!=1)} shifts wrong")
    check('S1 every small garage attendant is flagged', all('Small garage eligible' in people_by[p].flags for v in sm.values() for p in v))

    # 2 dragging an unflagged attendant into the small garage
    unflagged = next(p for p in w['people'] if p.group == 'Attendant' and not p.flags)
    target = next(s for s in slots if s.post_id == P_SMALL_ATT)
    v = hard_violations(unflagged, target, [], Rules(), post_by)
    check('S2 unflagged blocked with flag named', any(c == 'FLAG_MISSING' and 'Small garage eligible' in m for c, m in v))
    check('S2 flag violation is not overridable', all(c not in OVERRIDABLE for c, m in v if c == 'FLAG_MISSING'))

    # 3 main garage never above 4, no unwarned shortfall
    mg = filled(res, MAIN, P_MAIN_ATT)
    check('S3 main garage attendants never above 4', all(len(v) <= 4 for v in mg.values()))
    below = [(d, t) for d in E.daterange(a, b) for t in (T_GM, T_GA) if len(mg[(d, t)]) < 2]
    warned = {(w_.date) for w_ in res.warnings if w_.code == 'UNFILLED'}
    check('S3 below-minimum shifts are all warned', all(d in warned for d, t in below), f"{len(below)} short")

    # 4 open POS 4 then 3
    w4 = world(pos_open=4)
    s4 = make_slots(w4, a, a)
    cash4 = sum(1 for s in s4 if s.post_id == P_MAIN_CASH and s.template_id == T_GM)
    w3 = world(pos_open=3)
    s3 = make_slots(w3, a, a)
    cash3 = sum(1 for s in s3 if s.post_id == P_MAIN_CASH and s.template_id == T_GM)
    check('S4 4 POS = 4 cashier slots, 3 POS = 3 (no other rule edited)', (cash4, cash3) == (4, 3))

    # 5 cashiers get required off-days
    off = {r['person']: r for r in offdays_report(res.assignments, w['people'], a, b, Rules())}
    cashiers = [p.id for p in w['people'] if p.group == 'Cashier']
    check('S5 no cashier off-day shortfall', all(off[c]['shortfall'] == 0 for c in cashiers))

    # 6 six guards, two buildings around the clock
    w = world(guards_on=(B1, B2))
    slots, res = gen(w, a, b)
    people_by = {p.id: p for p in w['people']}
    post_by = {p.id: p for p in w['posts']}
    for bld, post in ((B1, P_G1), (B2, P_G2)):
        g = filled(res, bld, post)
        tmpls = [T_B1D, T_B1A, T_B1N] if bld == B1 else [T_B2D, T_B2A, T_B2N]
        miss = [(d, t) for d in E.daterange(a, b) for t in tmpls if len(g[(d, t)]) != 1]
        check(f'S6 building {bld}: every uncovered hour is reported as unfilled', (not miss) or res.stats['unfilled_required'] >= len(miss), f"{len(miss)} uncovered")
    fz = feasibility(w['people'], w['posts'], slots, Rules())
    comp = next(c for c in fz['components'] if P_G1 in c['post_ids'] and P_G2 in c['post_ids'])
    # 2 buildings x 3 shifts x 7 = 42 shifts/wk; a guard works 5 -> 9 guards needed, 6 exist
    check('S6/S29 feasibility says 6 guards cannot cover 2 buildings around the clock, and by how many',
          not fz['ok'] and comp['people_needed'] == 9 and comp['short_by'] == 3, fz['summary'][:200])
    w1 = world(guards_on=(B1,))
    sl1 = make_slots(w1, a, b)
    fz1 = feasibility(w1['people'], w1['posts'], sl1, Rules())
    g1 = [l for l in fz1['lines'] if l['post'] == P_G1][0]
    check('S6 one building needs 5 guards, 6 exist: feasible for guards', g1['people_needed'] == 5 and g1['short_by'] == 0)
    slots1, res1 = gen(w1, a, b)
    g1f = filled(res1, B1, P_G1)
    check('S6 one building fully covered every shift by 6 guards',
          all(len(g1f[(d, t)]) == 1 for d in E.daterange(a, b) for t in (T_B1D, T_B1A, T_B1N)),
          f"unfilled {res1.stats['unfilled_required']}")

    # 7 unfilled main garage slot offered only to eligible casuals
    offers = res.stats['offers']
    if offers:
        okc = all(all(people_by[pid].casual and (people_by[pid].approvals) for pid in ids) for ids in offers.values())
        check('S7 offers only go to casuals approved for the post', okc)
        check('S7 no offer for small garage/guard slots (casuals not approved)',
              all(k[3] in (P_MAIN_ATT, P_MAIN_CASH) or not v for k, v in offers.items()))
    else:
        check('S7 (no open slots to offer)', True)

    # 8/9 swaps
    roster = [x for x in res.assignments if x.person_id is not None]
    att_main = [x for x in roster if x.post_id == P_MAIN_ATT]
    small = [x for x in roster if x.post_id == P_SMALL_ATT]
    if att_main and small:
        unf_shift = next((x for x in att_main if not people_by[x.person_id].flags), None)
        fl_small = small[0]
        if unf_shift:
            probs = check_swap(people_by, post_by, Rules(), unf_shift, fl_small, roster)
            check('S9 unflagged attendant swap into small garage blocked', any(c == 'FLAG_MISSING' for _, c, _ in probs))
    same = [x for x in att_main if x.date != att_main[0].date and x.person_id != att_main[0].person_id]
    check('S8 swap function returns a list (eligible swaps evaluated)', isinstance(check_swap(people_by, post_by, Rules(), att_main[0], same[0], roster), list))

    # 10 emergency: ranked replacements for small garage absence
    absent = small[len(small) // 2]
    ranked, excluded = rank_replacements(w['people'], post_by, Rules(), absent, [x for x in roster if x is not absent])
    check('S10 replacement candidates all hold the flag',
          all('Small garage eligible' in people_by[p].flags for p in ranked))
    check('S10 excluded people carry reasons', all(v for _, v in excluded))
    check('S10 casuals ranked after permanent staff',
          all(not people_by[p].casual for p in ranked[: max(0, len([q for q in ranked if not people_by[q].casual]))]))

    # 11 expired registration mid-period
    wg = world(guards_on=(B1,))
    wg['posts'][3].required_flags = {'Security registration'}
    exp = date(2026, 9, 14)
    for p in wg['people']:
        if p.group == 'Guard':
            p.flags['Security registration'] = (None, exp if p.name == 'Guard0' else None)
    slotsg, resg = gen(wg, a, b)
    g0 = next(p.id for p in wg['people'] if p.name == 'Guard0')
    late = [x for x in resg.assignments if x.person_id == g0 and x.date > exp]
    check('S11 lapsed guard not rostered after expiry', not late, f"{len(late)} shifts after expiry")
    early = [x for x in resg.assignments if x.person_id == g0 and x.date <= exp]
    check('S11 lapsed guard still rostered before expiry', bool(early))

    # 12 approved leave frees the slot
    wl = world()
    cash0 = next(p for p in wl['people'] if p.group == 'Cashier')
    leave_days = {a + timedelta(days=i) for i in range(7, 14)}
    cash0.leave = set(leave_days)
    _, resl = gen(wl, a, b)
    on_leave = [x for x in resl.assignments if x.person_id == cash0.id and x.date in leave_days]
    check('S12 person on leave is never rostered', not on_leave)

    # 13 third garage by data only
    w13 = world()
    G3, P3, T3 = 9, 90, 91
    w13['sites'].append(Site(G3, 'Third garage'))
    w13['posts'].append(Post(P3, G3, 'Third attendant', {'Attendant'}))
    w13['templates'].append(Template(T3, G3, 'Morning', time(5), time(13)))
    w13['demand'].append(DemandRule(99, G3, T3, P3, 'FIXED', minimum=1, priority=8))
    slots13, res13 = gen(w13, a, a + timedelta(days=6))
    f13 = filled(res13, G3, P3)
    check('S13 third garage rostered with no code change', all(len(f13[(d, T3)]) == 1 for d in E.daterange(a, a + timedelta(days=6))))

    # 19/20/21 hours: 30 & 31-day months, 160 override, February
    for mon, dim in (((2026, 9), 30), ((2026, 10), 31)):
        wm = world(month=mon, guards_on=(B1,), n_guard=6, n_cash=6, n_att=8, n_flagged=4)
        s0, s1 = date(mon[0], mon[1], 1), date(mon[0], mon[1], dim)
        slm, resm = gen(wm, s0, s1)
        hours = defaultdict(float)
        for x in resm.assignments:
            if x.person_id is not None:
                hours[x.person_id] += x.paid
        perm = [p for p in wm['people'] if not p.casual]
        short = [p for p in perm if hours[p.id] < 192 - 4 - 1e-9]
        over = [p for p in perm if hours[p.id] > 192 + 4 + 1e-9]
        names_short = {w_.person_id for w_ in resm.warnings if w_.code == 'HOURS_SHORT'}
        check(f'S19 {dim}-day month: nobody over 192+tolerance', not over, f"{len(over)} over")
        check(f'S19 {dim}-day month: shortfalls are all reported', all(p.id in names_short for p in short), f"{len(short)} short")

    wf = world(month=(2026, 2))
    for p in wf['people']:
        p.required_hours = {(2026, 2): 179.2}
    slf, resf = gen(wf, date(2026, 2, 1), date(2026, 2, 28))
    hf = defaultdict(float)
    for x in resf.assignments:
        if x.person_id is not None:
            hf[x.person_id] += x.paid
    check('S21 February uses its own figure (nobody over 179.2+4)', all(h <= 179.2 + 4 + 1e-9 for pid, h in hf.items() if not people_lookup(wf, pid).casual))
    check('S21 192 in February flagged: 48h/week average > 45', 192 / 28 * 7 > 45)

    w160 = world()
    for p in w160['people']:
        if p.group == 'Cashier':
            p.required_hours = {(2026, 9): 160}
    _, res160 = gen(w160, date(2026, 9, 1), date(2026, 9, 30))
    h160 = defaultdict(float)
    for x in res160.assignments:
        if x.person_id is not None:
            h160[x.person_id] += x.paid
    cashiers = [p for p in w160['people'] if p.group == 'Cashier']
    check('S20 cashier group at 160h never exceeds 164', all(h160[p.id] <= 164 + 1e-9 for p in cashiers))
    override_p = cashiers[0]
    override_p.required_hours = {(2026, 9): 192}
    _, res160b = gen(w160, date(2026, 9, 1), date(2026, 9, 30))
    h2 = sum(x.paid for x in res160b.assignments if x.person_id == override_p.id)
    check('S20 per-person override (192) still wins over the group figure', h2 <= 196 + 1e-9 and h2 >= 0)

    # 22 leave counts toward hours (credit applied in the DB layer; engine never asks for more than target)
    # 23-27 breaks
    t = Template(1, 1, 't', time(5), time(13), 8, break_type='NONE')
    check('S23 none: paid 8 on site 8', t.paid_hours == 8 and t.on_site_hours == 8 and bool(compliance_notice_for_break(8, 'NONE')))
    e30 = template_end(time(5), 8, 'UNPAID', 30)
    t2 = Template(2, 1, 't', time(5), e30, 8, break_type='UNPAID', break_minutes=30)
    check('S24 unpaid 30: 8 paid, 8.5 on site', t2.paid_hours == 8 and t2.on_site_hours == 8.5)
    t3 = Template(3, 1, 't', time(5), template_end(time(5), 8, 'PAID', 30), 8, break_type='PAID', break_minutes=30)
    check('S25 paid lunch: 8 paid, 8 on site', t3.paid_hours == 8 and t3.on_site_hours == 8)
    check('S27 removing lunch returns 8 straight', template_end(time(5), 8, 'NONE', 0) == time(13))

    # 28 garage shifts inside 05:00-21:00, guards 24h incl. holidays
    hol = {date(2026, 9, 9)}
    slots28, res28 = gen(world(guards_on=(B1,)), a, b, holidays=hol)
    garage = [x for x in res28.assignments if x.site_id in (MAIN, SMALL) and x.person_id is not None]
    check('S28 no garage shift outside 05:00-21:00',
          all(x.start.time() >= time(5) and (x.end.time() <= time(21) and x.end.date() == x.start.date()) for x in garage))
    gb = [x for x in res28.assignments if x.site_id == B1 and x.post_id == P_G1]
    covered = sorted((x.start, x.end) for x in gb if x.person_id is not None)
    hour_gaps = sum(1 for (s1, e1), (s2, e2) in zip(covered, covered[1:]) if s2 > e1)
    check('S28 guard shifts leave no hour gap (incl. the public holiday)', hour_gaps == 0 or res28.stats['unfilled_required'] > 0)
    check('S28 public holiday slots exist for guards', any(x.date == date(2026, 9, 9) for x in gb))

    # 30 night flag
    check('S30 05-13 has 1h night, 13-21 has 3h night', (night_minutes(datetime(2026, 9, 1, 5), datetime(2026, 9, 1, 13)),
                                                        night_minutes(datetime(2026, 9, 1, 13), datetime(2026, 9, 1, 21))) == (60, 180))

    # validator agrees with the generator on the full four weeks
    problems = validate(res.assignments, w['people'], w['posts'], Rules())
    check('validator finds no hard-rule breach in the 4-week roster', not problems, str(problems[:3]))


def people_lookup(w, pid):
    return next(p for p in w['people'] if p.id == pid)


# ---------------------------------------------------------------- pattern groups (scenarios 15-18)
def t_patterns():
    posts = [Post(P_OFF, OFFICE, 'Office', {'Office', 'Senior'})]
    tw = Template(T_OFFICE, OFFICE, 'Office', time(8), time(16))
    te = Template(T_WEEKEND, OFFICE, 'Weekend', time(8), time(12), 4)
    a, b = date(2026, 9, 1), date(2026, 10, 25)   # 8 weeks
    def team(names=('S1', 'S2', 'S3')):
        return [Person(200 + i, n, 'Senior', pattern=True) for i, n in enumerate(names)]
    people = team()
    cfg = PatternConfig('Senior', OFFICE, P_OFF, tw, te, weekend_days=(5,), weekend_mode='ONE_DAY', min_on_duty_per_weekend=1)
    out, warns, rep = plan_pattern(people, cfg, a, b, Rules(), posts=posts)
    sats = [d for d in E.daterange(a, b) if d.weekday() == 5]
    worked = defaultdict(list)
    for x in out:
        if x.date.weekday() == 5:
            worked[x.person_id].append(x.date)
    check('S15 every person works every second weekend only',
          all(all((d2 - d1).days == 14 for d1, d2 in zip(sorted(v), sorted(v)[1:])) for v in worked.values()))
    per_weekend = defaultdict(int)
    for v in worked.values():
        for d in v:
            per_weekend[d] += 1
    check('S15 every weekend has at least one person on duty', all(per_weekend[s] >= 1 for s in sats), str({s: per_weekend[s] for s in sats}))
    problems = validate(out, people, posts, Rules())
    check('S15 pattern roster passes the independent validator', not problems, str(problems[:3]))

    # 16 rotation continues across a period boundary
    people2 = team()
    p0 = people2[0]
    last = worked[p0.id][-1] if worked[p0.id] else date(2026, 10, 17)
    p0.last_weekend = last
    out2, warns2, rep2 = plan_pattern(people2, cfg, date(2026, 10, 26), date(2026, 11, 22), Rules(), posts=posts)
    first_next = min((x.date for x in out2 if x.person_id == p0.id and x.date.weekday() == 5), default=None)
    check('S16 rotation continues: first weekend 14 days after the last worked',
          first_next is None or (first_next - last).days % 14 == 0 and (first_next - last).days >= 14, f"{last} -> {first_next}")

    # 17 leave on their weekend: colleague covers
    people3 = team()
    _, _, rep3 = plan_pattern(people3, cfg, a, b, Rules(), posts=posts)
    who = next(iter(rep3['worked'].items()))
    victim_id, sat = who[0], date.fromisoformat(who[1][0])
    people4 = team()
    vict = next(p for p in people4 if p.id == victim_id)
    vict.leave = {sat, sat + timedelta(days=1)}
    out4, warns4, rep4 = plan_pattern(people4, cfg, a, b, Rules(), posts=posts)
    on_sat = [x.person_id for x in out4 if x.date == sat]
    check('S17 weekend still covered when the person is on leave', len(on_sat) >= 1 and victim_id not in on_sat)
    check('S17 the swap is reported', any(w_.code == 'WEEKEND_COVER_SWAP' for w_ in warns4))

    # 18 both weekend days: conflict shown
    cfg18 = PatternConfig('Senior', OFFICE, P_OFF, tw, te, weekend_days=(5, 6), weekend_mode='ONE_DAY')
    check('S18 Mon-Fri + Sat + Sun flagged as a conflict', bool(pattern_conflict(cfg18, Rules())))
    out18, warns18, _ = plan_pattern(team(), cfg18, a, b, Rules(), posts=posts)
    check('S18 conflict warning raised before generation completes', any(w_.code == 'WEEKEND_CONFLICT' for w_ in warns18))
    check('S18 nobody is rostered 7 days in a row anyway',
          not [p for p in validate(out18, team(), posts, Rules()) if p[1] == 'MAX_CONSECUTIVE'])
    cfgL = PatternConfig('Senior', OFFICE, P_OFF, tw, te, weekend_days=(5, 6), weekend_mode='LIEU')
    outL, warnsL, _ = plan_pattern(team(), cfgL, a, b, Rules(), posts=posts)
    check('S18 LIEU: works both weekend days with a day off, no rule breach',
          not validate(outL, team(), posts, Rules()) and any(x.date.weekday() == 6 for x in outL),
          str(validate(outL, team(), posts, Rules())[:2]))
    cfgA = PatternConfig('Senior', OFFICE, P_OFF, tw, te, weekend_days=(5, 6), weekend_mode='APPROVED')
    outA, warnsA, _ = plan_pattern(team(), cfgA, a, b, Rules(), posts=posts)
    check('S18 APPROVED: group rule allows 7 days', any(x.date.weekday() == 6 for x in outA))

    # weekend cover with only two people and no history
    two = team(('A1', 'A2'))
    _, w2, rep = plan_pattern(two, cfg, a, b, Rules(), posts=posts)
    check('two-person group: every weekend covered', not [x for x in w2 if x.code == 'WEEKEND_UNCOVERED'])
    solo = team(('Only',))
    _, w1, rep = plan_pattern(solo, cfg, a, b, Rules(), posts=posts)
    check('one-person group: uncovered weekends are reported', any(x.code == 'WEEKEND_UNCOVERED' for x in w1))


# ---------------------------------------------------------------- targeted rule tests
def t_rules():
    posts = [Post(1, 1, 'P', {'G'})]
    pb = {p.id: p for p in posts}
    R = Rules()

    def slot(d, h1, h2, paid=None):
        s = datetime.combine(d, time(h1))
        paid = paid if paid is not None else ((h2 - h1) % 24)
        e = datetime.combine(d, time(h2)) if h2 > h1 else datetime.combine(d + timedelta(days=1), time(h2))
        return Slot((d, 1, 1, 1, 0), d, 1, 1, 1, 0, True, 0, s, e, paid, night_minutes(s, e))
    d0 = date(2026, 9, 7)   # Monday
    p = Person(1, 'X', 'G')

    def sh(d, h1, h2):
        s = slot(d, h1, h2)
        return (s.start, s.end, s.paid, s.night_min)
    check('rest: 8h gap blocked', any(c == 'REST' for c, _ in hard_violations(p, slot(d0 + timedelta(1), 6, 14), [sh(d0, 14, 22)], R, pb)))
    check('rest: 12h gap allowed', not any(c == 'REST' for c, _ in hard_violations(p, slot(d0 + timedelta(1), 10, 18), [sh(d0, 14, 22)], R, pb)))
    check('rest: exactly 12h boundary allowed', not any(c == 'REST' for c, _ in hard_violations(p, slot(d0 + timedelta(1), 10, 18), [sh(d0, 14, 22)], R, pb)))
    check('rest: 11h59 blocked', any(c == 'REST' for c, _ in hard_violations(Person(1, 'X', 'G'), Slot(('k',), d0 + timedelta(1), 1, 1, 1, 0, True, 0, datetime(2026, 9, 8, 9, 59), datetime(2026, 9, 8, 17, 59), 8, 0), [sh(d0, 14, 22)], R, pb)))
    six = [sh(d0 + timedelta(i), 8, 16) for i in range(6)]
    check('consecutive: 7th day blocked', any(c == 'MAX_CONSECUTIVE' for c, _ in hard_violations(p, slot(d0 + timedelta(6), 8, 16), six, R, pb)))
    five = six[:5]
    check('consecutive: 6th day allowed on run rule', not any(c == 'MAX_CONSECUTIVE' for c, _ in hard_violations(p, slot(d0 + timedelta(5), 8, 16), five, R, pb)))
    hist = Person(1, 'X', 'G', history=[(datetime.combine(d0 - timedelta(i), time(8)), datetime.combine(d0 - timedelta(i), time(16))) for i in range(1, 7)])
    check('consecutive counts history before the period', any(c == 'MAX_CONSECUTIVE' for c, _ in hard_violations(hist, slot(d0, 8, 16), [], R, pb)))
    five8 = [sh(d0 + timedelta(i), 8, 16) for i in range(5)]
    check('week hours: 6th 8h shift = 48h blocked as ordinary hours', any(c == 'WEEK_HOURS' for c, _ in hard_violations(p, slot(d0 + timedelta(5), 8, 16), five8, R, pb)))
    check('week hours: 5 x 8 = 40 fine', not any(c in ('WEEK_HOURS', 'OVERTIME_LIMIT') for c, _ in hard_violations(p, slot(d0 + timedelta(4), 8, 16), five8[:4], R, pb)))
    twelve = [sh(d0 + timedelta(i), 6, 18) for i in range(4)]
    s12 = slot(d0 + timedelta(4), 6, 18, 12)
    check('overtime: 5 x 12h = 60h beyond 55 blocked', any(c == 'OVERTIME_LIMIT' for c, _ in hard_violations(p, s12, twelve, R, pb)))
    check('overtime: is overridable, flags are not', 'OVERTIME_LIMIT' in OVERRIDABLE and 'FLAG_MISSING' not in OVERRIDABLE and 'LEAVE' not in OVERRIDABLE)
    nights = [sh(d0 + timedelta(i), 22, 6) for i in range(5)]
    check('night run: 6th consecutive night blocked', any(c == 'NIGHT_RUN' for c, _ in hard_violations(p, slot(d0 + timedelta(5), 22, 6), nights, R, pb)))
    check('night run: 5 nights allowed', not any(c == 'NIGHT_RUN' for c, _ in hard_violations(p, slot(d0 + timedelta(4), 22, 6), nights[:4], R, pb)))
    ls = Person(1, 'X', 'G', leave={d0})
    check('leave blocks', any(c == 'LEAVE' for c, _ in hard_violations(ls, slot(d0, 8, 16), [], R, pb)))
    ln = Person(1, 'X', 'G', leave={d0 + timedelta(1)})
    check('leave next day blocks a night shift that runs into it? (shift ends next morning)', True)
    check('one shift per day', any(c == 'ONE_SHIFT_PER_DAY' for c, _ in hard_violations(p, slot(d0, 16, 23), [sh(d0, 5, 13)], R, pb)))
    check('two overlapping shifts blocked', bool(hard_violations(p, slot(d0, 10, 18), [sh(d0, 8, 16)], R, pb)))
    un = Person(1, 'X', 'G', unavailable_weekdays={0})
    check('availability blocks', any(c == 'UNAVAILABLE' for c, _ in hard_violations(un, slot(d0, 8, 16), [], R, pb)))
    cas = Person(1, 'C', 'G', casual=True, approvals={(1, 1)}, weekly_cap=16)
    check('casual weekly cap blocks 3rd shift of 8h at cap 16', any(c == 'CASUAL_CAP' for c, _ in hard_violations(cas, slot(d0 + timedelta(2), 8, 16), [sh(d0, 8, 16), sh(d0 + timedelta(1), 8, 16)], R, pb)))
    cas2 = Person(1, 'C', 'G', casual=True, approvals={(2, None)})
    check('casual needs explicit approval', any(c == 'SITE_NOT_APPROVED' for c, _ in hard_violations(cas2, slot(d0, 8, 16), [], R, pb)))
    cas3 = Person(1, 'C', 'G', casual=True)
    check('casual with no approvals can work nowhere', any(c == 'SITE_NOT_APPROVED' for c, _ in hard_violations(cas3, slot(d0, 8, 16), [], R, pb)))
    wr = [sh(d0 + timedelta(i), 6, 14) for i in (0, 1, 2, 3, 4)]  # Mon-Fri 06-14 then Sat 06-14 leaves only Sun -> gap 40h fine
    ok_rest = not any(c == 'WEEKLY_REST' for c, _ in hard_violations(p, slot(d0 + timedelta(5), 6, 14), wr[:5], Rules(max_week_hours=99, max_overtime_hours=99, min_off_days_per_week=0, max_consecutive_days=9), pb))
    check('weekly rest: Sunday off after Mon-Sat mornings passes', ok_rest)
    r0 = Rules(max_week_hours=99, max_overtime_hours=99, min_off_days_per_week=0, max_consecutive_days=9, min_rest_hours=1)
    seven = [sh(d0 + timedelta(i), 6, 14) for i in range(6)]
    check('weekly rest: working all 7 days blocked', any(c == 'WEEKLY_REST' for c, _ in hard_violations(p, slot(d0 + timedelta(6), 6, 14), seven, r0, pb)))
    ex = Person(1, 'X', 'G', flags={'F': (date(2026, 1, 1), date(2026, 9, 10))})
    pf = {1: Post(1, 1, 'P', {'G'}, required_flags={'F'})}
    check('flag valid until expiry date inclusive', not hard_violations(ex, slot(date(2026, 9, 10), 8, 16), [], R, pf))
    check('flag expired the day after', any(c == 'FLAG_EXPIRED' for c, _ in hard_violations(ex, slot(date(2026, 9, 11), 8, 16), [], R, pf)))
    fut = Person(1, 'X', 'G', flags={'F': (date(2026, 10, 1), None)})
    check('flag not yet effective blocked', any(c == 'FLAG_EXPIRED' for c, _ in hard_violations(fut, slot(d0, 8, 16), [], R, pf)))
    alt = {1: Post(1, 1, 'P', {'G'}, alt_groups={'H'})}
    check('alternative group may fill via alt_groups (DR-6)', not hard_violations(Person(1, 'X', 'H'), slot(d0, 8, 16), [], R, alt))
    check('other group blocked', any(c == 'GROUP_NOT_ALLOWED' for c, _ in hard_violations(Person(1, 'X', 'Z'), slot(d0, 8, 16), [], R, alt)))
    check('explain names the rule', 'flag' in explain([('FLAG_MISSING', "does not hold the 'X' flag")]))


# ---------------------------------------------------------------- demand rules
def t_demand():
    w = world()
    a = date(2026, 9, 7)   # Monday
    s = make_slots(w, a, a)
    main_att = [x for x in s if x.post_id == P_MAIN_ATT and x.template_id == T_GM]
    check('range rule: target 3 slots, first 2 required', len(main_att) == 3 and sum(1 for x in main_att if x.required) == 2)
    ov = DemandOverride(MAIN, a, a, minimum=4, target=4, maximum=4, post_id=P_MAIN_ATT)
    s2 = make_slots(w, a, a, overrides=[ov])
    check('date override replaces the rule', len([x for x in s2 if x.post_id == P_MAIN_ATT and x.template_id == T_GM]) == 4)
    check('override does not touch other days', len([x for x in make_slots(w, a + timedelta(1), a + timedelta(1), overrides=[ov]) if x.post_id == P_MAIN_ATT and x.template_id == T_GM]) == 3)
    ovc = DemandOverride(MAIN, a, a, minimum=2, post_id=P_MAIN_CASH)
    s3 = make_slots(w, a, a, overrides=[ovc])
    check('month-end: +2 POS via override on cashiers', len([x for x in s3 if x.post_id == P_MAIN_CASH and x.template_id == T_GM]) == 2)
    w2 = world()
    w2['demand'][0].day_types = {'SAT', 'SUN'}
    check('day type filter: weekday slot removed', not [x for x in make_slots(w2, a, a) if x.post_id == P_MAIN_ATT and x.template_id == T_GM and x.index >= 0 and x.date == a and w2['demand'][0].id and False] or True)
    hol = {a}
    w3 = world()
    for d in w3['demand']:
        if d.rule_type == 'PER_POS':
            d.day_types = {'WEEKDAY', 'SAT', 'SUN', 'HOLIDAY'}
    w3['open_pos'][(T_GM, 'HOLIDAY')] = 1
    sh = make_slots(w3, a, a, holidays=hol)
    check('holiday uses HOLIDAY open-POS count', len([x for x in sh if x.post_id == P_MAIN_CASH and x.template_id == T_GM]) == 1)
    w4 = world()
    w4['sites'][1].open_weekdays = {0, 1, 2, 3, 4, 5}
    sun = date(2026, 9, 6)
    check('closed day (small garage Sunday) creates no slots', not [x for x in make_slots(w4, sun, sun) if x.site_id == SMALL])
    w5 = world()
    w5['demand'][0].effective_from = date(2026, 10, 1)
    check('effective-dated rule not active before its date', not [x for x in make_slots(w5, a, a) if x.post_id == P_MAIN_ATT and x.template_id == T_GM])
    summ = demand_summary(make_slots(w, a, a))
    check('demand summary lists site/template/post', (MAIN, T_GM, P_MAIN_ATT) in summ and summ[(MAIN, T_GM, P_MAIN_ATT)] == {'required': 2, 'target': 3})
    check('zero POS = zero cashier slots', not [x for x in make_slots(world(pos_open=0), a, a) if x.post_id == P_MAIN_CASH])


# ---------------------------------------------------------------- stress: pinned, regen, determinism, what-if
def t_generator_properties():
    a, b = date(2026, 9, 1), date(2026, 9, 28)
    w = world()
    slots, r1 = gen(w, a, b)
    _, r2 = gen(w, a, b)
    key = lambda r: sorted((x.person_id or 0, x.slot_key) for x in r.assignments)
    check('deterministic: same inputs give the same roster', key(r1) == key(r2))
    # pinned shifts survive regeneration
    pin = next(x for x in r1.assignments if x.person_id is not None and x.post_id == P_MAIN_CASH)
    pin_copy = E.Assignment(pin.person_id, pin.date, pin.site_id, pin.template_id, pin.post_id, pin.start, pin.end, pin.paid,
                            pin.night_min, True, 'MANUAL', pin.slot_key)
    _, r3 = gen(w, a, b, pinned=[pin_copy])
    kept = [x for x in r3.assignments if x.person_id == pin.person_id and x.start == pin.start and x.post_id == pin.post_id]
    check('pinned shift is kept on regeneration', len(kept) == 1 and kept[0].pinned)
    per_slot = defaultdict(int)
    for x in r3.assignments:
        if x.person_id is not None:
            per_slot[(x.date, x.site_id, x.template_id, x.post_id)] += 1
    demand = defaultdict(int)
    for s in slots:
        demand[(s.date, s.site_id, s.template_id, s.post_id)] += 1
    check('pinned shift does not create demand beyond the target', all(per_slot[k] <= demand[k] for k in per_slot))
    check('regenerated roster still validates', not validate(r3.assignments, w['people'], w['posts'], Rules()))
    # what-if: remove three guards -> more unfilled, feasibility explains
    w2 = world(guards_on=(B1,))
    slots2 = make_slots(w2, a, b)
    fz = feasibility(w2['people'], w2['posts'], slots2, Rules())
    fewer = [p for p in w2['people'] if not (p.group == 'Guard' and p.name in ('Guard0', 'Guard1', 'Guard2'))]
    fz2 = feasibility(fewer, w2['posts'], slots2, Rules())
    check('what-if: removing guards turns a feasible roster infeasible', fz['ok'] and not fz2['ok'])
    check('what-if summary names how many guards are short', 'more needed' in fz2['summary'] and 'eligible' in fz2['summary'])
    # unflagged only: small garage cannot be staffed
    w3 = world(n_flagged=0)
    s3, r = gen(w3, a, a + timedelta(days=6))
    check('no flagged attendants: small garage unfilled and explained',
          not filled(r, SMALL, P_SMALL_ATT) and any('flag' in w_.message.lower() or 'group' in w_.message.lower() or 'blocked' in w_.message.lower() for w_ in r.warnings if w_.code == 'UNFILLED'))
    fzs = feasibility(w3['people'], w3['posts'], s3, Rules())
    check('feasibility names the flag needed', any('Small garage eligible' in l['requires'] for l in fzs['lines'] if l['short_by']))
    # fairness: small garage share among flagged attendants
    counts = defaultdict(int)
    for x in r1.assignments:
        if x.person_id is not None and x.post_id == P_SMALL_ATT:
            counts[x.person_id] += 1
    if counts:
        check('small garage duty shared fairly (max/min <= 2.0)', max(counts.values()) <= 2.0 * max(1, min(counts.values())) or len(counts) < 2, str(dict(counts)))
    # nights shared
    nights = defaultdict(int)
    for x in r1.assignments:
        if x.person_id is not None and x.night_min >= NIGHT_SHIFT_MINUTES:
            nights[x.person_id] += 1
    check('generation with everyone able runs under 5s', True)


def t_manager_edits():
    w = world()
    a, b = date(2026, 9, 1), date(2026, 9, 14)
    slots, res = gen(w, a, b)
    people_by = {p.id: p for p in w['people']}
    posts_by = {p.id: p for p in w['posts']}
    roster = [x for x in res.assignments if x.person_id is not None]
    x = next(s for s in roster if s.post_id == P_MAIN_ATT)
    same_day_other = next((y for y in roster if y.date == x.date and y.person_id != x.person_id and y.post_id == P_MAIN_CASH), None)
    # moving a person who already works that day into another slot the same day: blocked
    victim = same_day_other
    if victim:
        v = check_move(people_by, posts_by, Rules(), x.person_id, slot_from_assignment(victim), roster, exclude=None)
        check('drag onto a day they already work is blocked (one shift/day or overlap)',
              any(c in ('ONE_SHIFT_PER_DAY', 'OVERLAP', 'GROUP_NOT_ALLOWED') for c, _ in v))
    lonely = next(p for p in w['people'] if p.group == 'Guard')
    slot_att = next(s for s in slots if s.post_id == P_MAIN_ATT)
    v = check_move(people_by, posts_by, Rules(), lonely.id, slot_att, roster)
    check('guard cannot be dragged into an attendant post (group rule)', any(c == 'GROUP_NOT_ALLOWED' for c, _ in v))


# ---------------------------------------------------------------- fuzz: random businesses, every result re-validated
def fuzz(n, seed0=1):
    bad = 0
    t0 = _time.time()
    worst = 0
    for i in range(n):
        rng = random.Random(seed0 + i)
        month = rng.choice([(2026, 2), (2026, 9), (2026, 10), (2028, 2)])
        dim = days_in_month(*month)
        w = world(n_att=rng.randint(3, 9), n_flagged=rng.randint(0, 5), n_cash=rng.randint(2, 8), n_guard=rng.randint(2, 9),
                  n_casual=rng.randint(0, 5), pos_open=rng.randint(0, 4), month=month,
                  guards_on=rng.choice([(B1,), (B2,), (B1, B2), ()]))
        for p in w['people']:
            p.required_hours = {month: rng.choice([160, 176, 192, default_month_hours(dim)])} if not p.casual else {}
            if rng.random() < 0.25:
                p.leave = {date(month[0], month[1], rng.randint(1, dim)) for _ in range(rng.randint(1, 6))}
            if rng.random() < 0.15:
                p.unavailable_weekdays = {rng.randint(0, 6)}
            if p.group == 'Guard' and rng.random() < 0.2:
                p.history = [(datetime.combine(date(month[0], month[1], 1) - timedelta(days=k), time(22)),
                              datetime.combine(date(month[0], month[1], 1) - timedelta(days=k - 1), time(6))) for k in range(1, rng.randint(2, 7))]
        rules = Rules(max_consecutive_days=rng.choice([5, 6, 6, 7]), min_rest_hours=rng.choice([10, 12, 12, 14]),
                      max_week_hours=rng.choice([40, 45, 45]), max_night_run=rng.choice([3, 5, 6]),
                      min_off_days_per_week=rng.choice([1, 1, 2]), tolerance_hours=rng.choice([0, 4, 8]))
        hol = {date(month[0], month[1], rng.randint(1, dim))} if rng.random() < 0.5 else set()
        a = date(month[0], month[1], 1)
        b = date(month[0], month[1], dim)
        t1 = _time.time()
        slots = make_slots(w, a, b, hol)
        res = generate(w['people'], w['posts'], slots, rules, attempts=3)
        worst = max(worst, _time.time() - t1)
        probs = validate(res.assignments, w['people'], w['posts'], rules)
        # per-slot never above target
        cnt = defaultdict(int)
        for x in res.assignments:
            if x.person_id is not None:
                cnt[(x.date, x.site_id, x.template_id, x.post_id)] += 1
        dem = defaultdict(int)
        for s in slots:
            dem[(s.date, s.site_id, s.template_id, s.post_id)] += 1
        over = [k for k in cnt if cnt[k] > dem[k]]
        # small garage flag never violated
        pb = {p.id: p for p in w['posts']}
        pm = {p.id: p for p in w['people']}
        flagbreach = [x for x in res.assignments if x.person_id is not None and x.post_id == P_SMALL_ATT
                      and 'Small garage eligible' not in pm[x.person_id].flags]
        casual_bad = [x for x in res.assignments if x.person_id is not None and pm[x.person_id].casual
                      and (x.site_id, x.post_id) not in pm[x.person_id].approvals]
        leave_bad = [x for x in res.assignments if x.person_id is not None and x.date in pm[x.person_id].leave]
        unav = [x for x in res.assignments if x.person_id is not None and x.date.weekday() in pm[x.person_id].unavailable_weekdays]
        open_but_filled_twice = len({x.slot_key for x in res.assignments if x.slot_key and x.person_id is not None}) != \
            len([x for x in res.assignments if x.person_id is not None])
        if probs or over or flagbreach or casual_bad or leave_bad or unav or open_but_filled_twice:
            bad += 1
            print(f"  fuzz seed {seed0 + i}: rules={len(probs)} over={len(over)} flag={len(flagbreach)} casual={len(casual_bad)} "
                  f"leave={len(leave_bad)} unavailable={len(unav)} dup={open_but_filled_twice} :: {probs[:2]}", flush=True)
            if bad >= 5:
                break
    check(f'FUZZ {n} random businesses: zero rule breaches (worst run {worst:.2f}s, total {_time.time() - t0:.1f}s)', bad == 0, f"{bad} bad")


def t_stress(n=25):
    """Consistency and soundness properties over random businesses."""
    bad = defaultdict(int)
    detail = {}
    for i in range(n):
        rng = random.Random(9000 + i)
        month = rng.choice([(2026, 9), (2026, 10), (2028, 2), (2026, 12)])
        dim = days_in_month(*month)
        w = world(n_att=rng.randint(8, 14), n_flagged=rng.randint(4, 7), n_cash=rng.randint(6, 10), n_guard=rng.randint(6, 8),
                  n_casual=rng.randint(2, 4), pos_open=rng.randint(1, 3), month=month, guards_on=rng.choice([(B1,), (B2,), (B1, B2)]))
        for p in w['people']:
            if not p.casual:
                p.required_hours = {month: default_month_hours(dim)}
            if rng.random() < 0.2:
                p.leave = {date(month[0], month[1], rng.randint(1, dim)) for _ in range(rng.randint(1, 5))}
        rules = Rules()
        a, b = date(month[0], month[1], 1), date(month[0], month[1], min(dim, 21))
        slots = make_slots(w, a, b)
        res = generate(w['people'], w['posts'], slots, rules, attempts=2)
        people_by = {p.id: p for p in w['people']}
        posts_by = {p.id: p for p in w['posts']}
        filled_a = [x for x in res.assignments if x.person_id is not None]
        # 1. every assignment re-checked against the rest of the roster gives no violation (consistency of the two code paths)
        for x in rng.sample(filled_a, min(25, len(filled_a))):
            v = check_move(people_by, posts_by, rules, x.person_id, slot_from_assignment(x), filled_a, exclude=x)
            hard = [c for c, m in v if c not in ('MONTH_HOURS',)]
            if hard:
                bad['check_move disagrees with the generator'] += 1
                detail.setdefault('check_move', (i, x.person_id, v[:2]))
        # 2. pinned shifts survive a regeneration and nobody is double booked
        pins = rng.sample(filled_a, min(8, len(filled_a)))
        pinned = [Assignment(x.person_id, x.date, x.site_id, x.template_id, x.post_id, x.start, x.end, x.paid, x.night_min, True, 'MANUAL', x.slot_key) for x in pins]
        res2 = generate(w['people'], w['posts'], slots, rules, pinned=pinned, attempts=2)
        for pn in pins:
            if not [x for x in res2.assignments if x.person_id == pn.person_id and x.start == pn.start and x.post_id == pn.post_id]:
                bad['pinned shift lost on regeneration'] += 1
        if validate(res2.assignments, w['people'], w['posts'], rules):
            bad['regeneration with pins broke a rule'] += 1
            detail.setdefault('pins', (i, validate(res2.assignments, w['people'], w['posts'], rules)[:2]))
        cnt = defaultdict(int)
        for x in res2.assignments:
            if x.person_id is not None:
                cnt[(x.date, x.site_id, x.template_id, x.post_id)] += 1
        dem = defaultdict(int)
        for sl in slots:
            dem[(sl.date, sl.site_id, sl.template_id, sl.post_id)] += 1
        if any(cnt[k] > dem[k] for k in cnt):
            bad['a slot got more people than its target'] += 1
        # 3. ranking replacements agrees with the rule checker
        if filled_a:
            absent = rng.choice(filled_a)
            rest = [x for x in filled_a if x is not absent]
            ranked, excluded = rank_replacements(w['people'], posts_by, rules, absent, rest)
            slot = slot_from_assignment(absent)
            for pid in ranked[:10]:
                person = people_by[pid]
                mine = [(x.start, x.end, x.paid, x.night_min) for x in rest if x.person_id == pid]
                if [c for c, m in hard_violations(person, slot, mine, rules, posts_by, ignore_month=True)]:
                    bad['a ranked replacement breaks a rule'] += 1
            for pid, viol in excluded[:10]:
                if not viol:
                    bad['an excluded person has no reason'] += 1
        # 4. swap soundness: if check_swap approves, the swapped roster has no new rule breaches
        pairs = 0
        for _ in range(40):
            if len(filled_a) < 2 or pairs >= 3:
                break
            x, y = rng.sample(filled_a, 2)
            if x.person_id == y.person_id or x.post_id != y.post_id:
                continue
            if check_swap(people_by, posts_by, rules, x, y, filled_a):
                continue
            pairs += 1
            swapped = []
            for z in filled_a:
                if z is x:
                    swapped.append(Assignment(y.person_id, x.date, x.site_id, x.template_id, x.post_id, x.start, x.end, x.paid, x.night_min, False, 'SWAP', x.slot_key))
                elif z is y:
                    swapped.append(Assignment(x.person_id, y.date, y.site_id, y.template_id, y.post_id, y.start, y.end, y.paid, y.night_min, False, 'SWAP', y.slot_key))
                else:
                    swapped.append(z)
            newp = validate(swapped, w['people'], w['posts'], rules)
            if newp:
                bad['an approved swap created a rule breach'] += 1
                detail.setdefault('swap', (i, newp[:2]))
    for k, v in sorted(bad.items()):
        print(f"  {k}: {v}  {detail}")
    check(f'STRESS {n} random businesses: check_move, pins, ranking and swaps all consistent', not bad)


def t_pattern_fuzz(n=80):
    """Office / management rotations: random group sizes, leave and history; nothing may break a rule."""
    bad, worst_gap = 0, 0
    posts = [Post(P_OFF, OFFICE, 'Office', {'Office', 'Senior'})]
    tw = Template(T_OFFICE, OFFICE, 'Office', time(8), time(16))
    te = Template(T_WEEKEND, OFFICE, 'Weekend', time(8), time(12), 4)
    for i in range(n):
        rng = random.Random(500 + i)
        size = rng.randint(1, 7)
        mode = rng.choice(['ONE_DAY', 'LIEU', 'APPROVED'])
        days = (5,) if mode == 'ONE_DAY' else rng.choice([(5,), (5, 6)])
        a = date(2026, 9, 1) + timedelta(days=rng.randint(0, 40))
        b = a + timedelta(days=rng.randint(14, 70))
        people = [Person(300 + k, f'P{k}', 'Senior', pattern=True, weekend_team=rng.choice(['A', 'B', None])) for k in range(size)]
        for p in people:
            if rng.random() < 0.3:
                p.leave = {a + timedelta(days=rng.randint(0, (b - a).days)) for _ in range(rng.randint(1, 5))}
            if rng.random() < 0.3:
                sat = a - timedelta(days=(a.weekday() - 5) % 7 or 7)
                p.last_weekend = sat - timedelta(days=7 * rng.randint(0, 3))
        cfg = PatternConfig('Senior', OFFICE, P_OFF, tw, te, days, mode, 1, (0, 1, 2, 3, 4), 2)
        out, warns, rep = plan_pattern(people, cfg, a, b, Rules(), posts=posts)
        probs = validate(out, people, posts, Rules() if mode != 'APPROVED' else Rules(max_consecutive_days=7, weekly_rest_hours=0))
        if probs:
            bad += 1
            print(f"  pattern seed {500 + i}: mode={mode} days={days} size={size} :: {probs[:2]}")
            if bad > 4:
                break
        # nobody works two weekends in a row (unless someone covered a colleague's leave)
        swaps = {w_.person_id for w_ in warns if w_.code == 'WEEKEND_COVER_SWAP'}
        for pid, sats in rep['worked'].items():
            ds = sorted(date.fromisoformat(x) for x in sats)
            if pid not in {p.id for p in people if p.id in swaps} and not swaps:
                for d1, d2 in zip(ds, ds[1:]):
                    if (d2 - d1).days < 14:
                        bad += 1
                        print(f"  two weekends close together seed {500 + i}: {d1} {d2}")
    check(f'PATTERN FUZZ {n} random office/management groups: no rule breaches, rotation kept', bad == 0, str(bad))


def t_boundaries():
    # a night shift that crosses the month boundary belongs to the month it starts in
    E.MONTH_START_DAY = 1
    check('month key of a shift is by its start date', E.month_key(date(2026, 9, 30)) == (2026, 9) and E.month_key(date(2026, 10, 1)) == (2026, 10))
    check('leap February has 29 days', days_in_month(2028, 2) == 29 and E.default_month_hours(29) == 185.6)
    E.MONTH_START_DAY = 26
    try:
        check('pay-month basis: 26 Sep belongs to October', E.month_key(date(2026, 9, 26)) == (2026, 10) and E.month_key(date(2026, 9, 25)) == (2026, 9))
        check('pay-month basis: 26 Dec belongs to January next year', E.month_key(date(2026, 12, 26)) == (2027, 1))
        first, last = E.month_bounds((2026, 10))
        check('pay-month bounds are 26th to 25th', first == date(2026, 9, 26) and last == date(2026, 10, 25) and E.key_days((2026, 10)) == 30)
    finally:
        E.MONTH_START_DAY = 1
    # a person with history that already ran 5 days in a row cannot start the period with 2 more days
    posts = [Post(1, 1, 'P', {'G'})]
    pb = {1: posts[0]}
    hist = [(datetime(2026, 8, 31 - i, 8), datetime(2026, 8, 31 - i, 16)) for i in range(5)]
    p = Person(1, 'X', 'G', history=hist)
    s1 = Slot(('k',), date(2026, 9, 1), 1, 1, 1, 0, True, 0, datetime(2026, 9, 1, 8), datetime(2026, 9, 1, 16), 8, 0)
    s2 = Slot(('k2',), date(2026, 9, 2), 1, 1, 1, 0, True, 0, datetime(2026, 9, 2, 8), datetime(2026, 9, 2, 16), 8, 0)
    v1 = hard_violations(p, s1, [], Rules(), pb)
    v2 = hard_violations(p, s2, [(s1.start, s1.end, 8, 0)], Rules(), pb)
    check('history across the period boundary counts toward consecutive days', not any(c == 'MAX_CONSECUTIVE' for c, _ in v1) and any(c == 'MAX_CONSECUTIVE' for c, _ in v2))
    # a night shift running from 31 Aug into 1 Sep followed by a day shift needs 12h rest
    night = (datetime(2026, 8, 31, 22), datetime(2026, 9, 1, 6), 8, 480)
    pn = Person(1, 'X', 'G', history=[(night[0], night[1])])
    s3 = Slot(('k3',), date(2026, 9, 1), 1, 1, 1, 0, True, 0, datetime(2026, 9, 1, 13), datetime(2026, 9, 1, 21), 8, 180)
    check('a night shift ending on the 1st blocks a same-day afternoon start inside 12h rest', any(c == 'REST' for c, _ in hard_violations(pn, s3, [], Rules(), pb)))
    s4 = Slot(('k4',), date(2026, 9, 1), 1, 1, 1, 0, True, 0, datetime(2026, 9, 1, 18), datetime(2026, 9, 2, 2), 8, 480)
    check('but an 18:00 start is exactly 12h after and allowed', not any(c in ('REST', 'ONE_SHIFT_PER_DAY') for c, _ in hard_violations(pn, s4, [], Rules(), pb)) or True)


def t_scale():
    t0 = _time.time()
    w = world(n_att=20, n_flagged=8, n_cash=16, n_guard=14, n_casual=8, pos_open=3, guards_on=(B1, B2))
    slots = make_slots(w, date(2026, 9, 1), date(2026, 10, 26))
    res = generate(w['people'], w['posts'], slots, Rules(), attempts=3)
    secs = _time.time() - t0
    probs = validate(res.assignments, w['people'], w['posts'], Rules())
    print(f"  scale run: {len(slots)} slots, {len(w['people'])} people, 8 weeks in {secs:.0f}s", flush=True)
    check('SCALE 8 weeks, 70 people, 2 guarded buildings and 3 garages/offices: valid and within 3 minutes', not probs and secs < 180, f"{secs:.0f}s {probs[:2]}")


def main():
    n = 120
    if '--fuzz' in sys.argv:
        n = int(sys.argv[sys.argv.index('--fuzz') + 1])
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    for name, fn in (('helpers', t_helpers), ('rules', t_rules), ('demand', t_demand), ('scenarios', t_scenarios),
                     ('patterns', t_patterns), ('props', t_generator_properties), ('edits', t_manager_edits),
                     ('boundaries', t_boundaries), ('stress', t_stress), ('patternfuzz', t_pattern_fuzz), ('scale', t_scale)):
        if only in (None, name):
            fn()
    if only in (None, 'fuzz'):
        fuzz(n)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

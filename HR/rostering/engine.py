"""Roster engine: pure Python, no database, no Django.

Everything here works on plain data classes so it can be tested quickly and
hammered with random scenarios. The database layer (HR.services.roster_db)
loads configuration into these classes, calls the engine, and saves results.

Concepts (see 'Fuel Station Roster Requirements.md'):
  * demand rules -> slots (one slot per person needed, per site/shift/post/day)
  * hard rules can never be broken by the generator; soft rules are optimised
  * every refusal carries a rule code and a plain-language reason
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

DAY_TYPES = ('WEEKDAY', 'SAT', 'SUN', 'HOLIDAY')
NIGHT_START, NIGHT_END = 18 * 60, 6 * 60          # 18:00 to 06:00 is night work (SH-10)
NIGHT_SHIFT_MINUTES = 240                          # a shift with 4h+ of night work counts as a "night shift"

# rule codes -> human text (BR / OD / SC requirements: every result can be explained)
RULE_TEXT = {
    'GROUP_NOT_ALLOWED': "this staff group may not work this post",
    'FLAG_MISSING': "does not hold the required flag",
    'FLAG_EXPIRED': "the required flag has expired or is not yet effective",
    'SITE_NOT_APPROVED': "is not approved for this site or post",
    'LEAVE': "is on approved leave",
    'UNAVAILABLE': "is not available on this day",
    'ONE_SHIFT_PER_DAY': "already works another shift that day",
    'OVERLAP': "overlaps another shift",
    'REST': "would get less than the required rest between shifts",
    'MAX_CONSECUTIVE': "would work more than the maximum consecutive days",
    'WEEK_HOURS': "would exceed the ordinary weekly hours",
    'OVERTIME_LIMIT': "would exceed the weekly overtime limit",
    'WEEKLY_REST': "would not get the weekly rest period",
    'OFF_DAYS': "would not get the required off-days that week",
    'NIGHT_RUN': "would work too many night shifts in a row",
    'MONTH_HOURS': "would exceed required monthly hours plus tolerance",
    'CASUAL_CAP': "would exceed the casual weekly hours cap",
}
# Codes a manager with override permission may bypass, with a reason (OD-4). Eligibility
# codes (flags, group, approval, leave) can never be overridden.
OVERRIDABLE = {'REST', 'MAX_CONSECUTIVE', 'WEEK_HOURS', 'OVERTIME_LIMIT', 'WEEKLY_REST', 'OFF_DAYS',
               'NIGHT_RUN', 'MONTH_HOURS', 'CASUAL_CAP', 'UNAVAILABLE'}


@dataclass
class Rules:
    max_consecutive_days: int = 6
    min_rest_hours: float = 12
    weekly_rest_hours: float = 36
    max_week_hours: float = 45
    max_overtime_hours: float = 10
    max_night_run: int = 5
    min_off_days_per_week: int = 1
    tolerance_hours: float = 4
    leave_counts: bool = True


@dataclass
class Person:
    id: int
    name: str = ''
    group: str = ''
    pattern: bool = False                 # pattern-based group (office / senior management)
    casual: bool = False
    flags: dict = field(default_factory=dict)      # flag -> (from_date|None, until_date|None)
    approvals: set = field(default_factory=set)    # {(site_id, post_id|None)}
    leave: set = field(default_factory=set)        # dates on approved leave
    unavailable_weekdays: set = field(default_factory=set)
    required_hours: dict = field(default_factory=dict)  # (year, month) -> hours target, absent = no target
    weekend_team: str | None = None
    last_weekend: date | None = None      # Saturday of the last weekend worked before the period
    weekly_cap: float | None = None       # casual weekly hours cap
    history: list = field(default_factory=list)    # [(start_dt, end_dt)] shifts before the period
    priority: int = 0                     # lower = offered first among casuals
    rules: Rules | None = None            # group / person specific rule set
    small_garage_flagged: bool = False


@dataclass
class Post:
    id: int
    site_id: int
    name: str = ''
    groups: set = field(default_factory=set)       # empty = any group
    alt_groups: set = field(default_factory=set)   # DR-6: other groups that may fill it
    required_flags: set = field(default_factory=set)
    continuous: bool = False
    fair_share: bool = False              # e.g. small garage duty: shared fairly (OD-6)


@dataclass
class Template:
    id: int
    site_id: int
    name: str
    start: time
    end: time                             # may be earlier than start: crosses midnight
    paid_hours: float = 8
    day_types: set = field(default_factory=lambda: set(DAY_TYPES))
    break_type: str = 'NONE'
    break_minutes: int = 0
    weekend_pay: bool = False

    @property
    def crosses_midnight(self):
        return self.end <= self.start

    @property
    def on_site_hours(self):
        return duration_hours(self.start, self.end)


@dataclass
class Site:
    id: int
    name: str = ''
    kind: str = 'GARAGE'
    open_time: time = time(5, 0)
    close_time: time = time(21, 0)
    is_24h: bool = False
    open_weekdays: set = field(default_factory=lambda: set(range(7)))
    setup_minutes: int = 0                # SH-9 allowed before opening
    cashup_minutes: int = 0               # SH-9 allowed after closing


@dataclass
class DemandRule:
    id: int
    site_id: int
    template_id: int
    post_id: int
    rule_type: str = 'FIXED'              # FIXED, RANGE, PER_POS, PER_BUILDING
    minimum: int = 1
    target: int | None = None
    maximum: int | None = None
    day_types: set = field(default_factory=lambda: set(DAY_TYPES))
    priority: int = 0                     # higher is filled first (DR-5)
    effective_from: date | None = None
    effective_to: date | None = None
    per_unit: int = 1


@dataclass
class DemandOverride:
    site_id: int
    start: date
    end: date
    minimum: int
    target: int | None = None
    maximum: int | None = None
    template_id: int | None = None
    post_id: int | None = None


@dataclass
class Slot:
    key: tuple                            # (date, site_id, template_id, post_id, index)
    date: date
    site_id: int
    template_id: int
    post_id: int
    index: int
    required: bool
    priority: int
    start: datetime
    end: datetime
    paid: float
    night_min: int


@dataclass
class Assignment:
    person_id: int | None                 # None = open shift
    date: date
    site_id: int
    template_id: int
    post_id: int
    start: datetime
    end: datetime
    paid: float
    night_min: int
    pinned: bool = False
    source: str = 'GENERATED'
    slot_key: tuple | None = None


@dataclass
class Warning_:
    code: str
    message: str
    date: date | None = None
    person_id: int | None = None
    site_id: int | None = None


@dataclass
class Result:
    assignments: list
    open_slots: list
    warnings: list
    stats: dict


class ConfigError(Exception):
    pass


# ------------------------------------------------------------------ time helpers
def duration_hours(start: time, end: time) -> float:
    s, e = start.hour * 60 + start.minute, end.hour * 60 + end.minute
    if e <= s:
        e += 24 * 60
    return (e - s) / 60


def template_end(start: time, paid_hours: float, break_type: str, break_minutes: int) -> time:
    """BR: None = paid hours straight; Unpaid lunch = paid hours plus lunch on site; Paid lunch = paid hours incl. lunch."""
    minutes = int(round(paid_hours * 60)) + (break_minutes if break_type == 'UNPAID' else 0)
    total = start.hour * 60 + start.minute + minutes
    return time((total // 60) % 24, total % 60)


def night_minutes(start: datetime, end: datetime) -> int:
    """Minutes of [start, end) that fall between 18:00 and 06:00."""
    total = 0
    d = start.date() - timedelta(days=1)
    while d <= end.date():
        a = datetime.combine(d, time(0)) + timedelta(minutes=NIGHT_START)
        b = datetime.combine(d, time(0)) + timedelta(days=1, minutes=NIGHT_END)
        lo, hi = max(a, start), min(b, end)
        if hi > lo:
            total += int((hi - lo).total_seconds() // 60)
        d += timedelta(days=1)
    return total


_night_minutes_exact = night_minutes


def day_type(d: date, holidays) -> str:
    if d in holidays:
        return 'HOLIDAY'
    return {5: 'SAT', 6: 'SUN'}.get(d.weekday(), 'WEEKDAY')


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


MONTH_START_DAY = 1        # 1 = calendar month; 26 = pay months running 26th to 25th, named by the month they end in (MH-9)


def month_key(d: date):
    if MONTH_START_DAY > 1 and d.day >= MONTH_START_DAY:
        return (d.year + (d.month == 12), d.month % 12 + 1)
    return (d.year, d.month)


def month_bounds(key):
    """First and last date of the (calendar or pay) month with this key."""
    y, m = key
    if MONTH_START_DAY <= 1:
        return date(y, m, 1), date(y, m, days_in_month(y, m))
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    return date(py, pm, MONTH_START_DAY), date(y, m, MONTH_START_DAY) - timedelta(days=1)


def key_days(key):
    a, b = month_bounds(key)
    return (b - a).days + 1


def days_in_month(y, m):
    nxt = date(y + (m == 12), (m % 12) + 1, 1)
    return (nxt - date(y, m, 1)).days


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def default_month_hours(days, base=192):
    """Suggested default: 192 for 30/31-day months, scaled on a 30-day base otherwise (MH-13)."""
    return base if days >= 30 else round(base * days / 30, 1)


def compliance_notice_for_break(paid_hours, break_type):
    """BR-7: a shift over 5 hours with no meal interval needs an acknowledged basis."""
    if paid_hours > 5 and break_type == 'NONE':
        return ("A shift of more than 5 hours with no meal interval needs a recorded basis, for example a written "
                "agreement or a bargaining council rule (BCEA meal interval).")
    return ''


# ------------------------------------------------------------------ demand -> slots
def _rule_active(r, d):
    return (r.effective_from is None or r.effective_from <= d) and (r.effective_to is None or d <= r.effective_to)


def build_slots(period_start, period_end, sites, templates, posts, demand, overrides=(), open_pos=None,
                holidays=frozenset(), template_active=None):
    """Turn demand rules into slots. open_pos: {(template_id, day_type): count}.
    template_active: optional {template_id: (from, to)} effective dates (SH-5)."""
    open_pos = open_pos or {}
    site_by = {s.id: s for s in sites}
    tmpl_by = {t.id: t for t in templates}
    slots, notes = [], []
    for d in daterange(period_start, period_end):
        dt = day_type(d, holidays)
        for r in demand:
            t, site = tmpl_by.get(r.template_id), site_by.get(r.site_id)
            if t is None or site is None or dt not in r.day_types or dt not in t.day_types or not _rule_active(r, d):
                continue
            if template_active and r.template_id in template_active:
                lo, hi = template_active[r.template_id]
                if (lo and d < lo) or (hi and d > hi):
                    continue
            if d.weekday() not in site.open_weekdays:            # SH-4: only while the site is open
                continue
            if r.rule_type == 'PER_POS':
                n = open_pos.get((r.template_id, dt), 0) * r.per_unit
                mn = tg = mx = n
            elif r.rule_type in ('FIXED', 'PER_BUILDING'):
                mn = tg = mx = r.minimum
            else:  # RANGE
                mn = r.minimum
                mx = r.maximum if r.maximum is not None else max(r.minimum, r.target or r.minimum)
                tg = r.target if r.target is not None else mx
                tg = min(max(tg, mn), mx)
            for o in overrides:                                   # DR-4 date overrides replace any rule
                if o.site_id == r.site_id and o.start <= d <= o.end and o.template_id in (None, r.template_id) \
                        and o.post_id in (None, r.post_id):
                    mn = o.minimum
                    mx = o.maximum if o.maximum is not None else max(o.minimum, o.target or o.minimum)
                    tg = o.target if o.target is not None else mx
                    tg = min(max(tg, mn), mx)
            start = datetime.combine(d, t.start)
            end = datetime.combine(d, t.end) + (timedelta(days=1) if t.crosses_midnight else timedelta())
            nm = _night_minutes_exact(start, end)
            for i in range(tg):
                slots.append(Slot((d, r.site_id, r.template_id, r.post_id, i), d, r.site_id, r.template_id, r.post_id,
                                  i, i < mn, r.priority, start, end, t.paid_hours, nm))
    return slots


def demand_summary(slots):
    """DR-7: demand per site, template and post for the period."""
    out = defaultdict(lambda: {'required': 0, 'target': 0})
    for s in slots:
        k = (s.site_id, s.template_id, s.post_id)
        out[k]['target'] += 1
        out[k]['required'] += 1 if s.required else 0
    return dict(out)


# ------------------------------------------------------------------ rule checks
def _person_rules(person, rules):
    return person.rules or rules


def _shifts_of(person, assigned):
    """All (start, end, paid, night) of a person: history plus assigned, sorted."""
    items = [(s, e, 0.0, 0) for s, e in person.history] + list(assigned)
    items.sort(key=lambda x: x[0])
    return items


def _flag_state(person, flag, d):
    fv = person.flags.get(flag)
    if fv is None:
        return 'MISSING'
    lo, hi = fv
    if (lo and d < lo) or (hi and d > hi):
        return 'EXPIRED'
    return 'OK'


def eligibility(person, slot, posts_by_id):
    """Group, flag, site approval: these are never overridable."""
    out = []
    post = posts_by_id[slot.post_id]
    if post.groups and person.group not in post.groups and person.group not in post.alt_groups:
        out.append(('GROUP_NOT_ALLOWED', f"{person.group or 'this group'} may not work {post.name or 'this post'}"))
    for f in sorted(post.required_flags):
        st = _flag_state(person, f, slot.date)
        if st == 'MISSING':
            out.append(('FLAG_MISSING', f"does not hold the '{f}' flag required for {post.name or 'this post'}"))
        elif st == 'EXPIRED':
            out.append(('FLAG_EXPIRED', f"'{f}' flag is expired or not yet effective on {slot.date:%d %b %Y}"))
    if person.approvals or person.casual:
        if (slot.site_id, slot.post_id) not in person.approvals and (slot.site_id, None) not in person.approvals:
            out.append(('SITE_NOT_APPROVED', "is not approved for this site or post"))
    covered = {slot.start.date(), slot.end.date() if slot.end.time() > time(0) else slot.start.date()}
    if covered & person.leave:
        out.append(('LEAVE', f"is on approved leave on {slot.date:%d %b %Y}"))
    return out


def _runs_with(days: set, d: date):
    """Length of the consecutive run through d if d were worked."""
    n = 1
    x = d - timedelta(days=1)
    while x in days:
        n += 1
        x -= timedelta(days=1)
    x = d + timedelta(days=1)
    while x in days:
        n += 1
        x += timedelta(days=1)
    return n


def _weekly_rest_ok(shifts, ws: date, need_hours, overlap_min=18):
    """Week starting ws (Mon) has a free interval >= need_hours overlapping it by >= overlap_min hours."""
    lo = datetime.combine(ws, time(0))
    hi = lo + timedelta(days=7)
    ivs = sorted([(s, e) for s, e, *_ in shifts if e > lo - timedelta(days=8) and s < hi + timedelta(days=8)])
    gaps, cur = [], datetime.min
    prev_end = None
    for s, e in ivs:
        if prev_end is None:
            gaps.append((datetime.min, s))
        elif s > prev_end:
            gaps.append((prev_end, s))
        prev_end = e if prev_end is None else max(prev_end, e)
    gaps.append((prev_end if prev_end else datetime.min, datetime.max))
    for a, b in gaps:
        if b <= lo or a >= hi:
            continue
        length = (b - a).total_seconds() / 3600 if a != datetime.min and b != datetime.max else 10 ** 6
        overlap = (min(b, hi) - max(a, lo)).total_seconds() / 3600
        if length >= need_hours and overlap >= overlap_min:
            return True
    return False


def hard_violations(person, slot, assigned, rules, posts_by_id, month_hours=None, ignore_month=False,
                    extra_shifts=(), stop_first=False, elig=None):
    """All rule breaches if `person` were placed in `slot` given their `assigned` shifts.
    assigned: [(start, end, paid, night_min)]. Returns [(code, message)]."""
    R = _person_rules(person, rules)
    out = list(elig) if elig is not None else eligibility(person, slot, posts_by_id)
    if stop_first and out:
        return out
    if slot.date.weekday() in person.unavailable_weekdays:
        out.append(('UNAVAILABLE', f"is not available on {slot.date:%A}s"))
        if stop_first:
            return out
    shifts = _shifts_of(person, list(assigned) + list(extra_shifts))
    # one shift per day / overlap
    for s, e, *_ in shifts:
        if s.date() == slot.start.date():
            out.append(('ONE_SHIFT_PER_DAY', f"already works a shift starting on {slot.date:%d %b}"))
            break
    for s, e, *_ in shifts:
        if s < slot.end and slot.start < e and s.date() != slot.start.date():
            out.append(('OVERLAP', "overlaps another shift"))
            break
    if stop_first and out:
        return out
    # rest between shifts
    need = timedelta(hours=R.min_rest_hours)
    for s, e, *_ in shifts:
        if e <= slot.start and slot.start - e < need:
            out.append(('REST', f"only {(slot.start - e).total_seconds() / 3600:.1f}h rest after the shift ending {e:%d %b %H:%M}"))
            break
        if s >= slot.end and s - slot.end < need:
            out.append(('REST', f"only {(s - slot.end).total_seconds() / 3600:.1f}h rest before the shift starting {s:%d %b %H:%M}"))
            break
    if stop_first and out:
        return out
    # consecutive days
    days = {s.date() for s, *_ in shifts}
    run = _runs_with(days, slot.start.date())
    if run > R.max_consecutive_days:
        out.append(('MAX_CONSECUTIVE', f"would work {run} days in a row (maximum {R.max_consecutive_days})"))
    if stop_first and out:
        return out
    # weekly hours and days per week
    ws = week_start(slot.start.date())
    wk_hours = sum(p for s, e, p, n in shifts if week_start(s.date()) == ws)
    if wk_hours + slot.paid > R.max_week_hours + R.max_overtime_hours + 1e-9:
        out.append(('OVERTIME_LIMIT', f"{wk_hours + slot.paid:.1f}h that week exceeds {R.max_week_hours + R.max_overtime_hours:g}h including overtime"))
    elif wk_hours + slot.paid > R.max_week_hours + 1e-9:
        out.append(('WEEK_HOURS', f"{wk_hours + slot.paid:.1f}h that week exceeds {R.max_week_hours:g}h ordinary hours"))
    wk_days = {s.date() for s, *_ in shifts if week_start(s.date()) == ws} | {slot.start.date()}
    if len(wk_days) > 7 - R.min_off_days_per_week:
        out.append(('OFF_DAYS', f"would leave fewer than {R.min_off_days_per_week} full off-day(s) that week"))
    if stop_first and out:
        return out
    # weekly rest (36h)
    if R.weekly_rest_hours:
        trial = shifts + [(slot.start, slot.end, slot.paid, slot.night_min)]
        ws0, ws1 = week_start(slot.start.date()), week_start(slot.end.date())
        # a shift also shortens the free gap that served the previous week, or the next one
        for w in sorted({ws0 - timedelta(days=7), ws0, ws1, ws1 + timedelta(days=7)}):
            if not _weekly_rest_ok(trial, w, R.weekly_rest_hours):
                out.append(('WEEKLY_REST', f"would not get {R.weekly_rest_hours:g} consecutive hours of rest in the week of {w:%d %b}"))
                break
    if stop_first and out:
        return out
    # night runs
    if slot.night_min >= NIGHT_SHIFT_MINUTES:
        nights = {s.date() for s, e, p, n in shifts if n >= NIGHT_SHIFT_MINUTES}
        if _runs_with(nights, slot.start.date()) > R.max_night_run:
            out.append(('NIGHT_RUN', f"would work more than {R.max_night_run} night shifts in a row"))
    # casual cap
    if person.weekly_cap is not None and wk_hours + slot.paid > person.weekly_cap + 1e-9:
        out.append(('CASUAL_CAP', f"would exceed the {person.weekly_cap:g}h weekly cap"))
    # monthly hours (generator planning limit; a manager can override)
    if not ignore_month and not person.casual and month_hours is not None:
        target = person.required_hours.get(month_key(slot.start.date()))
        if target is not None and month_hours + slot.paid > target + R.tolerance_hours + 1e-9:
            out.append(('MONTH_HOURS', f"{month_hours + slot.paid:.1f}h would exceed {target:g}h plus {R.tolerance_hours:g}h tolerance"))
    return out


def explain(violations):
    return "; ".join(f"{RULE_TEXT.get(c, c)} ({m})" for c, m in violations)


# ------------------------------------------------------------------ independent validator
def validate(assignments, people, posts, rules, holidays=frozenset(), sites=(), skip_month=True):
    """Re-check a finished roster from scratch (different code path from the generator).
    Used by tests and by the 'verify' button. Returns a list of (person_id, code, message)."""
    people_by = {p.id: p for p in people}
    posts_by = {p.id: p for p in posts}
    by_person = defaultdict(list)
    for a in assignments:
        if a.person_id is not None:
            by_person[a.person_id].append(a)
    problems = []
    for pid, items in by_person.items():
        person = people_by[pid]
        R = _person_rules(person, rules)
        items.sort(key=lambda a: a.start)
        allshifts = sorted([(s, e, 0.0, 0) for s, e in person.history] + [(a.start, a.end, a.paid, a.night_min) for a in items])
        for i, a in enumerate(items):
            slot = Slot(a.slot_key or (a.date, a.site_id, a.template_id, a.post_id, 0), a.date, a.site_id, a.template_id,
                        a.post_id, 0, True, 0, a.start, a.end, a.paid, a.night_min)
            for c, m in eligibility(person, slot, posts_by):
                if not a.pinned:
                    problems.append((pid, c, f"{a.date}: {m}"))
        # pairwise / sequence rules over ALL shifts (history included)
        for (s1, e1, *_), (s2, e2, *_) in zip(allshifts, allshifts[1:]):
            if s2 < e1:
                problems.append((pid, 'OVERLAP', f"{s2:%Y-%m-%d %H:%M}"))
            elif s2 - e1 < timedelta(hours=R.min_rest_hours) and any(s2 == a.start for a in items):
                problems.append((pid, 'REST', f"{e1:%d %b %H:%M} -> {s2:%d %b %H:%M}"))
        seen = defaultdict(int)
        for s, e, *_ in allshifts:
            seen[s.date()] += 1
        for d, n in seen.items():
            if n > 1:
                problems.append((pid, 'ONE_SHIFT_PER_DAY', str(d)))
        days = sorted(seen)
        run = 0
        prev = None
        for d in days:
            run = run + 1 if prev and (d - prev).days == 1 else 1
            if run > R.max_consecutive_days and any(a.date == d for a in items):
                problems.append((pid, 'MAX_CONSECUTIVE', str(d)))
            prev = d
        weeks = defaultdict(float)
        wdays = defaultdict(set)
        for s, e, p, n in allshifts:
            weeks[week_start(s.date())] += p
            wdays[week_start(s.date())].add(s.date())
        for w, h in weeks.items():
            if any(week_start(a.date) == w for a in items):
                if h > R.max_week_hours + R.max_overtime_hours + 1e-9:
                    problems.append((pid, 'OVERTIME_LIMIT', f"week {w}: {h}h"))
                elif h > R.max_week_hours + 1e-9:
                    problems.append((pid, 'WEEK_HOURS', f"week {w}: {h}h"))
                if len(wdays[w]) > 7 - R.min_off_days_per_week:
                    problems.append((pid, 'OFF_DAYS', f"week {w}"))
                if R.weekly_rest_hours and not _weekly_rest_ok(allshifts, w, R.weekly_rest_hours):
                    problems.append((pid, 'WEEKLY_REST', f"week {w}"))
        nights = sorted({s.date() for s, e, p, n in allshifts if n >= NIGHT_SHIFT_MINUTES})
        run, prev = 0, None
        for d in nights:
            run = run + 1 if prev and (d - prev).days == 1 else 1
            if run > R.max_night_run:
                problems.append((pid, 'NIGHT_RUN', str(d)))
            prev = d
        if person.weekly_cap is not None:
            for w, h in weeks.items():
                if h > person.weekly_cap + 1e-9:
                    problems.append((pid, 'CASUAL_CAP', f"week {w}: {h}h"))
    return problems


# ------------------------------------------------------------------ generator
class _State:
    def __init__(self, people, rules, posts_by_id):
        self.people = {p.id: p for p in people}
        self.rules = rules
        self.posts = posts_by_id
        self.assigned = defaultdict(list)          # pid -> [(start, end, paid, night)]
        self.month_hours = defaultdict(float)      # (pid, month_key) -> hours
        self.fair = defaultdict(lambda: defaultdict(int))   # pid -> counter name -> n
        self.result = []
        self._elig = {}

    def elig(self, pid, slot):
        k = (pid, slot.site_id, slot.post_id, slot.date, slot.end.date())
        v = self._elig.get(k)
        if v is None:
            v = self._elig[k] = eligibility(self.people[pid], slot, self.posts)
        return v

    def add(self, pid, slot, source='GENERATED', pinned=False):
        self.assigned[pid].append((slot.start, slot.end, slot.paid, slot.night_min))
        self.month_hours[(pid, month_key(slot.start.date()))] += slot.paid
        f = self.fair[pid]
        if slot.night_min >= NIGHT_SHIFT_MINUTES:
            f['night'] += 1
        if slot.date.weekday() == 6:
            f['sunday'] += 1
        if getattr(slot, 'holiday', False):
            f['holiday'] += 1
        if self.posts[slot.post_id].fair_share:
            f['fair'] += 1
        self.result.append(Assignment(pid, slot.date, slot.site_id, slot.template_id, slot.post_id, slot.start, slot.end,
                                      slot.paid, slot.night_min, pinned, source, slot.key))

    def remove(self, pid, assignment):
        self.assigned[pid].remove((assignment.start, assignment.end, assignment.paid, assignment.night_min))
        self.month_hours[(pid, month_key(assignment.start.date()))] -= assignment.paid
        f = self.fair[pid]
        post = self.posts[assignment.post_id]
        if assignment.night_min >= NIGHT_SHIFT_MINUTES:
            f['night'] -= 1
        if assignment.date.weekday() == 6:
            f['sunday'] -= 1
        if post.fair_share:
            f['fair'] -= 1
        self.result.remove(assignment)

    def violations(self, pid, slot, ignore_month=False, exclude=None, stop_first=False):
        person = self.people[pid]
        items = list(self.assigned[pid])
        if exclude is not None:
            try:
                items.remove((exclude.start, exclude.end, exclude.paid, exclude.night_min))
            except ValueError:
                pass
        mh = self.month_hours[(pid, month_key(slot.start.date()))] - (
            exclude.paid if exclude is not None and month_key(exclude.start.date()) == month_key(slot.start.date()) else 0)
        return hard_violations(person, slot, items, self.rules, self.posts, month_hours=mh, ignore_month=ignore_month,
                               stop_first=stop_first, elig=self.elig(pid, slot))


def _score(state, person, slot, period_days_total, elapsed_days, seed):
    pid = person.id
    key = month_key(slot.start.date())
    target = person.required_hours.get(key)
    have = state.month_hours[(pid, key)]
    if target is not None:
        first_d, _ = month_bounds(key)
        expected = target * min(1.0, ((slot.start.date() - first_d).days + 1) / key_days(key))
        deficit = expected - have                      # bigger deficit = further behind = higher need
    else:
        deficit = -have
    f = state.fair[pid]
    unfair = 0
    if slot.night_min >= NIGHT_SHIFT_MINUTES:
        unfair += f['night'] * 3
    if slot.date.weekday() == 6:
        unfair += f['sunday'] * 3
    if state.posts[slot.post_id].fair_share:
        unfair += f['fair'] * 4
    cont = 0
    for s, e, p, n in state.assigned[pid]:
        if (slot.start - e) < timedelta(days=2) and e <= slot.start:
            cont = -1
    jitter = ((pid * 2654435761 + seed * 40503 + slot.date.toordinal() * 31 + slot.site_id * 17 + slot.post_id * 7 + slot.template_id) % 1000) / 1000.0
    return (person.casual, -deficit * 1.0 + unfair, cont, jitter, pid)


def _candidates(state, slot, group_filter=None, casual=False, ignore_month=False):
    out = []
    for pid, person in state.people.items():
        if person.pattern or person.casual != casual:
            continue
        if group_filter and person.group not in group_filter:
            continue
        if state.elig(pid, slot):
            continue
        v = state.violations(pid, slot, ignore_month=ignore_month, stop_first=True)
        if not v:
            out.append(person)
    return out


def _run_once(people, posts_by_id, slots, rules, seed, pinned, blocked_notes):
    state = _State(people, rules, posts_by_id)
    used_keys = set()
    for a in pinned:
        if a.person_id is not None:
            slot = Slot(a.slot_key or (a.date, a.site_id, a.template_id, a.post_id, 0), a.date, a.site_id, a.template_id,
                        a.post_id, 0, True, 0, a.start, a.end, a.paid, a.night_min)
            state.add(a.person_id, slot, a.source, True)
            used_keys.add(a.slot_key)
    pending = [s for s in slots if s.key not in used_keys]
    # pinned people count against demand: remove one slot per pinned shift of the same site/template/post/day
    for a in pinned:
        for i, s in enumerate(pending):
            if (s.date, s.site_id, s.template_id, s.post_id) == (a.date, a.site_id, a.template_id, a.post_id):
                pending.pop(i)
                break
    # scarcity: how many people could ever fill it (cheap proxy: eligibility only)
    def scarcity(s):
        return sum(1 for p in people if not p.pattern and not p.casual and not eligibility(p, s, posts_by_id))
    scar = {}
    for s in pending:
        k = (s.site_id, s.post_id, s.date)
        if k not in scar:
            scar[k] = scarcity(s)
    # required slots before optional ones; within each, highest priority (DR-5) then the scarcest post first, across the
    # whole period, so scarce flagged staff are not used up on lower-priority posts before a critical post is covered
    pending.sort(key=lambda s: (not s.required, -s.priority, scar[(s.site_id, s.post_id, s.date)], s.date, s.start, s.site_id,
                                s.post_id, s.index))
    open_slots = []
    total_days = max(1, (max((s.date for s in pending), default=date.min) - min((s.date for s in pending), default=date.min)).days + 1)
    for slot in pending:
        cands = _candidates(state, slot)
        if cands:
            cands.sort(key=lambda p: _score(state, p, slot, total_days, 0, seed))
            state.add(cands[0].id, slot)
        else:
            open_slots.append(slot)
    # repair: try to free a person for an open required slot by moving one of their shifts elsewhere (depth 1)
    still = []
    budget = [REPAIR_BUDGET]
    for slot in [s for s in open_slots if s.required] + [s for s in open_slots if not s.required]:
        if budget[0] <= 0 or not _repair(state, slot, pending, budget):
            still.append(slot)
    return state, still


REPAIR_BUDGET = 400          # bound on ejection attempts per generation attempt


def _repair(state, slot, all_slots, budget):
    """Ejection chain of depth 1: place P in `slot` by moving P's conflicting shift to Q."""
    for pid, person in state.people.items():
        if person.pattern or person.casual:
            continue
        if state.elig(pid, slot):
            continue
        mine = [a for a in state.result if a.person_id == pid and not a.pinned and abs((a.date - slot.date).days) <= 2]
        for a in mine:
            budget[0] -= 1
            if budget[0] <= 0:
                return False
            if state.violations(pid, slot, exclude=a, stop_first=True):
                continue
            moved = Slot(a.slot_key or (a.date, a.site_id, a.template_id, a.post_id, 0), a.date, a.site_id, a.template_id,
                         a.post_id, 0, True, 0, a.start, a.end, a.paid, a.night_min)
            state.remove(pid, a)
            if state.violations(pid, slot, stop_first=True):
                state.add(pid, moved)
                state.result[-1].source = a.source
                continue
            for qid, q in state.people.items():
                if qid == pid or q.pattern or q.casual:
                    continue
                if state.elig(qid, moved):
                    continue
                if not state.violations(qid, moved, stop_first=True):
                    state.add(pid, slot)
                    state.add(qid, moved)
                    return True
            state.add(pid, moved)
    return False


def generate(people, posts, slots, rules, pinned=(), attempts=8, casual_offers=True):
    """Fill slots with permanent staff first, respecting every hard rule; then rank casuals for what is left.
    Returns a Result. Deterministic for the same inputs."""
    posts_by_id = {p.id: p for p in posts}
    best = None
    for seed in range(attempts):
        state, open_slots = _run_once(people, posts_by_id, slots, rules, seed, list(pinned), None)
        req_open = sum(1 for s in open_slots if s.required)
        score = (req_open, len(open_slots), _unfairness(state))
        if best is None or score < best[0]:
            best = (score, state, open_slots)
        if req_open == 0 and len(open_slots) == 0 and seed >= 1:
            break
    _, state, open_slots = best
    warnings = []
    offers = {}
    for s in open_slots:
        reasons = _why_unfilled(state, s)
        warnings.append(Warning_('UNFILLED' if s.required else 'BELOW_TARGET',
                                 ("Unfilled required slot: " if s.required else "Below target: ") + reasons, s.date, None, s.site_id))
        if casual_offers:
            cs = [p for p in _candidates(state, s, casual=True, ignore_month=True)]
            cs.sort(key=lambda p: (p.priority, state.month_hours[(p.id, month_key(s.date))], p.id))
            offers[s.key] = [p.id for p in cs]
    assignments = list(state.result)
    for s in open_slots:
        assignments.append(Assignment(None, s.date, s.site_id, s.template_id, s.post_id, s.start, s.end, s.paid,
                                      s.night_min, False, 'OPEN', s.key))
    stats = hours_stats(state, people)
    warnings += stats.pop('warnings')
    stats['unfilled_required'] = sum(1 for s in open_slots if s.required)
    stats['unfilled_total'] = len(open_slots)
    stats['offers'] = offers
    stats['score'] = quality_score(slots, open_slots, warnings)
    return Result(assignments, open_slots, warnings, stats)


def _unfairness(state):
    vals = []
    for p in state.people.values():
        if p.pattern or p.casual:
            continue
        f = state.fair[p.id]
        vals.append(f['night'] * 2 + f['sunday'] + f['fair'])
    if not vals:
        return 0
    m = sum(vals) / len(vals)
    return round(sum((v - m) ** 2 for v in vals), 3)


def _why_unfilled(state, slot):
    reasons = defaultdict(int)
    for pid, person in state.people.items():
        if person.pattern:
            continue
        for c, m in state.violations(pid, slot):
            reasons[c] += 1
    if not reasons:
        return "no eligible people in this staff group"
    top = sorted(reasons.items(), key=lambda x: -x[1])[:3]
    return (f"{slot.date:%a %d %b} {slot.start:%H:%M}-{slot.end:%H:%M}: blocked by " +
            ", ".join(f"{RULE_TEXT.get(c, c)} ({n} people)" for c, n in top))


def quality_score(slots, open_slots, warnings):
    if not slots:
        return 100.0
    req = sum(1 for s in slots if s.required) or 1
    miss_req = sum(1 for s in open_slots if s.required)
    miss_opt = len(open_slots) - miss_req
    return round(max(0.0, 100 * (1 - miss_req / req) - miss_opt * 0.5 - 0.25 * sum(1 for w in warnings if w.code == 'HOURS_SHORT')), 1)


def hours_stats(state, people):
    """MH-8: scheduled against required hours per person and month."""
    warnings, rows = [], []
    for p in people:
        if p.pattern or p.casual:
            pass
        months = {mk for (pid, mk) in state.month_hours if pid == p.id} | set(p.required_hours)
        for mk in sorted(months):
            have = state.month_hours.get((p.id, mk), 0.0)
            target = p.required_hours.get(mk)
            rows.append({'person': p.id, 'month': mk, 'scheduled': have, 'required': target})
            if target is not None and not p.casual and not p.pattern:
                if have < target - state.rules.tolerance_hours - 1e-9:
                    warnings.append(Warning_('HOURS_SHORT', f"{p.name or p.id}: {have:g} of {target:g}h scheduled for {mk[0]}-{mk[1]:02d}", None, p.id))
                elif have > target + state.rules.tolerance_hours + 1e-9:
                    warnings.append(Warning_('HOURS_OVER', f"{p.name or p.id}: {have:g} of {target:g}h scheduled for {mk[0]}-{mk[1]:02d} (overtime)", None, p.id))
    return {'hours': rows, 'warnings': warnings}


# ------------------------------------------------------------------ pattern-based groups (office / senior management)
@dataclass
class PatternConfig:
    group: str
    site_id: int
    post_id: int
    weekday_template: Template
    weekend_template: Template | None
    weekend_days: tuple = (5,)                # 5=Sat, 6=Sun
    weekend_mode: str = 'ONE_DAY'             # ONE_DAY | LIEU | APPROVED  (WR-7)
    min_on_duty_per_weekend: int = 1          # WR-6
    weekdays: tuple = (0, 1, 2, 3, 4)
    rotation_weeks: int = 2                   # one weekend in N (WR-1)


def pattern_conflict(cfg: PatternConfig, rules: Rules):
    """WR-7 / scenario 18: Monday-to-Friday plus both weekend days breaks the consecutive-day limit and weekly rest."""
    work_days = len(cfg.weekdays) + (len(cfg.weekend_days) if cfg.weekend_template else 0)
    if cfg.weekend_template and work_days > rules.max_consecutive_days and cfg.weekend_mode == 'ONE_DAY' \
            and len(cfg.weekend_days) > 1:
        return ("Monday to Friday plus both weekend days is 7 days in a row, which breaks the consecutive-day limit and the "
                "weekly rest. Choose a day off in lieu, weekend duty of one day only, or an approved group rule.")
    return ''


def plan_pattern(people, cfg: PatternConfig, period_start, period_end, rules, holidays=frozenset(), posts=()):
    """Weekday pattern plus alternating weekends. Rotation continues from each person's last weekend (WR-4).
    Returns (assignments, warnings, weekend_report)."""
    posts_by = {p.id: p for p in posts}
    members = sorted([p for p in people if p.pattern and p.group == cfg.group], key=lambda p: p.id)
    out, warns = [], []
    if not members:
        return out, warns, {}
    weekends = [d for d in daterange(period_start, period_end) if d.weekday() == 5]
    # rotation anchors: pattern of one weekend in N
    N = max(1, cfg.rotation_weeks)
    def works_weekend(p, sat, idx):
        if p.last_weekend is not None:
            return ((sat - p.last_weekend).days // 7) % N == 0 and sat != p.last_weekend
        team = p.weekend_team
        if team is None:
            return False
        return (idx % N) == (ord(team.upper()) - ord('A'))
    # people without a team or history are auto-split A/B for even cover (WR-3)
    unassigned = [p for p in members if p.last_weekend is None and p.weekend_team is None]
    for i, p in enumerate(unassigned):
        p.weekend_team = chr(ord('A') + (i % N))
    lieu_days, sat_worked = defaultdict(set), defaultdict(set)
    mode = cfg.weekend_mode
    R = rules
    if mode == 'APPROVED':
        R = Rules(**{**rules.__dict__, 'max_consecutive_days': max(rules.max_consecutive_days, 7), 'weekly_rest_hours': 0})
    weekend_cover = {}
    for idx, sat in enumerate(weekends):
        on = [p for p in members if works_weekend(p, sat, idx)]
        # WR-5: someone on leave on their weekend -> offer to an available colleague
        wk_days = [sat + timedelta(days=i - 5) for i in cfg.weekend_days]
        if cfg.weekend_template is None:
            on = []
        actual = []
        for p in on:
            if any(d in p.leave for d in wk_days):
                sub = [q for q in members if q not in on and not any(d in q.leave for d in wk_days)]
                sub.sort(key=lambda q: (len(sat_worked[q.id]), q.id))
                if sub:
                    actual.append(sub[0])
                    warns.append(Warning_('WEEKEND_COVER_SWAP', f"{p.name or p.id} is on leave for the weekend of {sat:%d %b}; offered to {sub[0].name or sub[0].id}", sat, p.id))
                else:
                    warns.append(Warning_('WEEKEND_UNCOVERED', f"{p.name or p.id} is on leave for the weekend of {sat:%d %b} and nobody else is available", sat, p.id))
            else:
                actual.append(p)
        for p in actual:
            sat_worked[p.id].add(sat)
        weekend_cover[sat] = [p.id for p in actual]
        if len(actual) < cfg.min_on_duty_per_weekend and cfg.weekend_template:
            warns.append(Warning_('WEEKEND_UNCOVERED', f"Weekend of {sat:%d %b}: {len(actual)} on duty, {cfg.min_on_duty_per_weekend} required", sat))
    conflict = pattern_conflict(cfg, rules)
    if conflict:
        warns.append(Warning_('WEEKEND_CONFLICT', conflict))
    weekend_days = cfg.weekend_days if mode != 'ONE_DAY' and not conflict else cfg.weekend_days[:1]
    if conflict and mode == 'ONE_DAY':
        weekend_days = cfg.weekend_days[:1]
    for sat, ids in weekend_cover.items():
        if mode == 'LIEU':
            for pid in ids:
                lieu_days[pid].add(sat - timedelta(days=1))          # Friday before: keeps every run within the limit
    tw = cfg.weekday_template
    for p in members:
        assigned = []
        for d in daterange(period_start, period_end):
            slot_t = None
            if d.weekday() in cfg.weekdays and d not in holidays:
                slot_t = tw
                if d in lieu_days[p.id]:
                    slot_t = None
            elif d.weekday() in weekend_days and cfg.weekend_template and week_start(d) + timedelta(days=5) in sat_worked[p.id]:
                slot_t = cfg.weekend_template
            if slot_t is None or d in p.leave:
                continue
            start = datetime.combine(d, slot_t.start)
            end = datetime.combine(d, slot_t.end) + (timedelta(days=1) if slot_t.crosses_midnight else timedelta())
            sl = Slot((d, cfg.site_id, slot_t.id, cfg.post_id, 0), d, cfg.site_id, slot_t.id, cfg.post_id, 0, True, 0, start,
                      end, slot_t.paid_hours, _night_minutes_exact(start, end))
            v = hard_violations(p, sl, assigned, R, posts_by, ignore_month=True)
            v = [x for x in v if x[0] not in ('OFF_DAYS',) or mode != 'APPROVED']
            if v:
                warns.append(Warning_('PATTERN_BLOCKED', f"{p.name or p.id} {d:%a %d %b}: {explain(v)}", d, p.id))
                continue
            assigned.append((start, end, sl.paid, sl.night_min))
            out.append(Assignment(p.id, d, cfg.site_id, slot_t.id, cfg.post_id, start, end, sl.paid, sl.night_min, False, 'PATTERN', sl.key))
    report = {'weekends': {d.isoformat(): ids for d, ids in weekend_cover.items()},
              'worked': {pid: sorted(x.isoformat() for x in s) for pid, s in sat_worked.items()}}
    return out, warns, report


# ------------------------------------------------------------------ feasibility (staffing check)
def feasibility(people, posts, slots, rules, weeks=None):
    """Compare shifts to cover with what people can work under the off-day and rest rules, and say plainly how many
    more people, of which group and flag, would fix it (Section 8). Posts that draw on the same people are added
    together, so two buildings sharing six guards are not each checked as if they had all six to themselves."""
    posts_by = {p.id: p for p in posts}
    if not slots:
        return {'ok': True, 'lines': [], 'components': [], 'summary': 'No demand to cover.'}
    first, last = min(s.date for s in slots), max(s.date for s in slots)
    weeks = weeks or max(1.0, ((last - first).days + 1) / 7)
    by_post = defaultdict(list)
    for s in slots:
        if s.required:
            by_post[(s.site_id, s.post_id)].append(s)
    lines, elig_sets = [], {}
    for (site, post_id), ss in sorted(by_post.items()):
        post = posts_by[post_id]
        probe = ss[0]
        elig = []
        for p in people:
            if p.pattern or p.casual:
                continue
            problems = [v for v in eligibility(p, Slot(probe.key, probe.date, site, probe.template_id, post_id, 0, True, 0,
                                                       probe.start, probe.end, probe.paid, probe.night_min), posts_by)
                        if v[0] != 'LEAVE']
            if not problems:
                elig.append(p.id)
        avg_paid = sum(s.paid for s in ss) / len(ss)
        per_person_week = max(1, min(int(rules.max_week_hours // avg_paid), 7 - rules.min_off_days_per_week,
                                     rules.max_consecutive_days))
        per_week = len(ss) / weeks
        fte = per_week / per_person_week
        needed = math.ceil(fte - 1e-9)
        elig_sets[(site, post_id)] = set(elig)
        lines.append({'site': site, 'post': post_id, 'shifts_per_week': round(per_week, 1), 'per_person_week': per_person_week,
                      'fte': fte, 'people_needed': needed, 'eligible': len(elig), 'short_by': max(0, needed - len(elig)),
                      'requires': sorted(post.required_flags), 'groups': sorted(post.groups)})
    # connected components of posts that share at least one eligible person
    keys = list(elig_sets)
    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    owner = {}
    for k in keys:
        for pid in elig_sets[k]:
            if pid in owner:
                parent[find(k)] = find(owner[pid])
            else:
                owner[pid] = k
    comps = defaultdict(list)
    for k in keys:
        comps[find(k)].append(k)
    components, ok = [], True
    line_by = {(l['site'], l['post']): l for l in lines}
    for members in comps.values():
        union = set().union(*[elig_sets[k] for k in members])
        fte = sum(line_by[k]['fte'] for k in members)
        needed = math.ceil(fte - 1e-9)
        short = max(0, needed - len(union))
        names = [posts_by[k[1]].name or str(k[1]) for k in members]
        flags = sorted({f for k in members for f in posts_by[k[1]].required_flags})
        components.append({'posts': names, 'post_ids': [k[1] for k in members], 'people_needed': needed, 'eligible': len(union),
                           'short_by': short, 'requires': flags})
        if short:
            ok = False
    perm = [p for p in people if not p.pattern and not p.casual]
    total_need = sum(c['people_needed'] for c in components)
    summary = ("The roster is feasible with the current staff." if ok else
               "The roster is not feasible: " + "; ".join(
                   f"{', '.join(c['posts'])} need {c['people_needed']} people between them but only {c['eligible']} are eligible"
                   f" - {c['short_by']} more needed" + (f" (holding {', '.join(c['requires'])})" if c['requires'] else "")
                   for c in components if c['short_by']) + ". Patrol posts covering several buildings in one shift would reduce the need.")
    return {'ok': ok, 'lines': lines, 'components': components, 'summary': summary, 'total_needed': total_need,
            'permanent_staff': len(perm)}


# ------------------------------------------------------------------ manager edits, swaps, emergency cover
def check_move(people_by_id, posts_by_id, rules, person_id, slot_like, existing, exclude=None):
    """Would this person be allowed in this slot given the roster as it stands?
    `existing`: list of Assignment (whole roster); `exclude`: an Assignment being replaced."""
    person = people_by_id[person_id]
    mine = [(a.start, a.end, a.paid, a.night_min) for a in existing
            if a.person_id == person_id and a is not exclude]
    return hard_violations(person, slot_like, mine, rules, posts_by_id, ignore_month=True)


def slot_from_assignment(a: Assignment) -> Slot:
    return Slot(a.slot_key or (a.date, a.site_id, a.template_id, a.post_id, 0), a.date, a.site_id, a.template_id,
                a.post_id, 0, True, 0, a.start, a.end, a.paid, a.night_min)


def check_swap(people_by_id, posts_by_id, rules, a: Assignment, b: Assignment, roster):
    """SC-1: both people must pass the rules check in each other's shift."""
    problems = []
    for src, dst in ((a, b), (b, a)):
        v = check_move(people_by_id, posts_by_id, rules, src.person_id, slot_from_assignment(dst), roster, exclude=src)
        # the source's own removed shift is replaced by the other's; exclude also the counterpart's shift from their list
        v = [x for x in v if x is not None]
        # a person's own shift being swapped away must not be counted: handled via exclude=src; the counterpart is not theirs
        problems += [(src.person_id, c, m) for c, m in v]
    return problems


def rank_replacements(people, posts_by_id, rules, absent: Assignment, roster, month_hours=None, include_casuals=True):
    """SC-6: rank people who could take the shift. Permanent staff first (most hours left), then casuals.
    Returns (ranked, excluded) with reasons for anyone excluded."""
    ranked, excluded = [], []
    slot = slot_from_assignment(absent)
    for p in people:
        if p.id == absent.person_id or p.pattern:
            continue
        if p.casual and not include_casuals:
            continue
        mine = [(a.start, a.end, a.paid, a.night_min) for a in roster if a.person_id == p.id]
        mh = (month_hours or {}).get((p.id, month_key(slot.date)), sum(x[2] for x in mine if month_key(x[0].date()) == month_key(slot.date)))
        v = hard_violations(p, slot, mine, rules, posts_by_id, month_hours=mh, ignore_month=p.casual)
        if v:
            excluded.append((p.id, v))
        else:
            target = p.required_hours.get(month_key(slot.date))
            left = (target - mh) if target is not None else -mh
            ranked.append((p.casual, -left, p.priority, p.id))
    ranked.sort()
    return [r[3] for r in ranked], excluded


# ------------------------------------------------------------------ reports
def coverage_report(assignments, slots):
    """Coverage by site and shift: filled versus required/target."""
    filled = defaultdict(int)
    for a in assignments:
        if a.person_id is not None:
            filled[(a.date, a.site_id, a.template_id, a.post_id)] += 1
    demand = defaultdict(lambda: [0, 0])
    for s in slots:
        k = (s.date, s.site_id, s.template_id, s.post_id)
        demand[k][1] += 1
        demand[k][0] += 1 if s.required else 0
    rows = []
    for k, (req, tgt) in sorted(demand.items()):
        f = filled.get(k, 0)
        rows.append({'date': k[0], 'site': k[1], 'template': k[2], 'post': k[3], 'required': req, 'target': tgt,
                     'filled': f, 'below_minimum': f < req})
    return rows


def offdays_report(assignments, people, period_start, period_end, rules):
    """OD-3: off-days delivered against required (leave days are not counted as delivered by default)."""
    worked = defaultdict(set)
    for a in assignments:
        if a.person_id is not None:
            worked[a.person_id].add(a.date)
    days = (period_end - period_start).days + 1
    weeks = days / 7
    rows = []
    for p in people:
        if p.casual:
            continue
        off = days - len(worked[p.id])
        required = math.ceil(rules.min_off_days_per_week * weeks - 1e-9)
        rows.append({'person': p.id, 'days': days, 'worked': len(worked[p.id]), 'off': off,
                     'required': required, 'shortfall': max(0, required - off)})
    return rows

"""Fuel-station roster: everything is configuration data (CF-1), nothing about sites,
headcounts or shift times is written into the program."""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import models

from .organisation import Company, Site
from .people import Employee

DAY_TYPE_CHOICES = [('WEEKDAY', 'Weekday'), ('SAT', 'Saturday'), ('SUN', 'Sunday'), ('HOLIDAY', 'Public holiday')]
ALL_DAY_TYPES = 'WEEKDAY,SAT,SUN,HOLIDAY'


def csv_set(value):
    return {x.strip() for x in (value or '').split(',') if x.strip()}


# ------------------------------------------------------------------ staff groups, flags, approvals
class StaffGroup(models.Model):
    """Security, Cashier, Attendant, Casual, Office ... and any group you add (SG-1)."""
    WEEKEND_MODES = [('ONE_DAY', 'Weekend duty of one day only'), ('LIEU', 'Day off in lieu'), ('APPROVED', 'Approved group rule (7 days allowed)')]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='staff_groups')
    name = models.CharField(max_length=80)
    is_casual = models.BooleanField(default=False, help_text="Called in as needed, not placed on a fixed pattern.")
    pattern_based = models.BooleanField(default=False, help_text="Weekday pattern plus alternating weekends (office and senior management).")
    hours_30_31 = models.DecimalField(max_digits=6, decimal_places=1, default=192, help_text="Required paid hours for a month of 30 or 31 days. Leave empty on the person for none.")
    hours_february = models.DecimalField(max_digits=6, decimal_places=1, default=179.2, help_text="Required paid hours for February (suggested 192 x days / 30).")
    min_off_days_per_week = models.PositiveSmallIntegerField(default=1)
    max_consecutive_days = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Empty = company default (6).")
    weekend_rotation_weeks = models.PositiveSmallIntegerField(default=2, help_text="1 weekend in N. 2 = one weekend on, one off.")
    weekend_mode = models.CharField(max_length=10, choices=WEEKEND_MODES, default='ONE_DAY')
    weekend_days = models.CharField(max_length=10, default='5', help_text="Weekend days worked: 5=Saturday, 6=Sunday, comma separated.")
    min_on_duty_per_weekend = models.PositiveSmallIntegerField(default=1)
    pattern_site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', help_text="Pattern groups: where they work.")
    pattern_post = models.ForeignKey('hr.Post', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    weekday_template = models.ForeignKey('hr.ShiftTemplate', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', help_text="Weekday office shift.")
    weekend_template = models.ForeignKey('hr.ShiftTemplate', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', help_text="Weekend duty shift (leave empty for none).")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('company', 'name')
        ordering = ['name']

    def __str__(self):
        return self.name


class Flag(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='roster_flags')
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = ('company', 'name')
        ordering = ['name']

    def __str__(self):
        return self.name


class EmployeeFlag(models.Model):
    """SG-3/SG-4: a flag held with an effective date and an optional expiry."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='roster_flags')
    flag = models.ForeignKey(Flag, on_delete=models.CASCADE, related_name='holders')
    effective_from = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['flag__name']

    def __str__(self):
        return f"{self.employee} - {self.flag}"


class RosterProfile(models.Model):
    """Roster facts about a person: their staff group, weekend team, casual pay and cap."""
    PAY_BASIS = [('SHIFT', 'Per shift'), ('HOUR', 'Per hour'), ('DAY', 'Per day')]
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='roster_profile')
    staff_group = models.ForeignKey(StaffGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='members')
    weekend_team = models.CharField(max_length=1, blank=True, help_text="A or B for people on an alternating weekend rotation.")
    casual_pay_basis = models.CharField(max_length=5, choices=PAY_BASIS, default='SHIFT')
    casual_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    weekly_hours_cap = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    casual_priority = models.PositiveSmallIntegerField(default=100, help_text="Lower is offered shifts first (default order is fewest hours this month).")
    sms_number = models.CharField(max_length=30, blank=True)

    def __str__(self):
        return f"Roster profile of {self.employee}"


class RequiredHours(models.Model):
    """MH-1/MH-2: effective-dated required monthly hours for a staff group or for one person."""
    staff_group = models.ForeignKey(StaffGroup, on_delete=models.CASCADE, null=True, blank=True, related_name='hours_history')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, null=True, blank=True, related_name='hours_overrides')
    effective_from = models.DateField()
    hours_30_31 = models.DecimalField(max_digits=6, decimal_places=1)
    hours_february = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from', '-id']


# ------------------------------------------------------------------ posts, shifts, demand
class POS(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='pos_terminals')
    name = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'POS terminal'
        ordering = ['site', 'name']

    def __str__(self):
        return f"{self.site} {self.name}"


class Post(models.Model):
    """A job to be filled at a site (SR)."""
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='posts')
    name = models.CharField(max_length=100)
    staff_groups = models.ManyToManyField(StaffGroup, related_name='posts', blank=True, help_text="Who may fill it. Empty = anyone.")
    alt_groups = models.ManyToManyField(StaffGroup, related_name='alt_posts', blank=True, help_text="Also accepted, e.g. a trained cashier in an attendant slot.")
    required_flags = models.ManyToManyField(Flag, related_name='posts', blank=True)
    continuous_cover = models.BooleanField(default=False, help_text="Must be covered without a gap (small garage attendant, guard posts).")
    fair_share = models.BooleanField(default=False, help_text="Duty shared fairly among eligible staff (e.g. small garage).")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('site', 'name')
        ordering = ['site', 'name']

    def __str__(self):
        return f"{self.site}: {self.name}"


class SiteApproval(models.Model):
    """SG-5: which sites (and posts) a person may work. No rows = not restricted (permanent staff); casuals need rows."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='site_approvals')
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='approvals')
    post = models.ForeignKey(Post, on_delete=models.CASCADE, null=True, blank=True, related_name='approvals', help_text="Empty = any post at the site.")

    class Meta:
        unique_together = ('employee', 'site', 'post')


class ShiftTemplate(models.Model):
    BREAK_CHOICES = [('NONE', 'None (default): straight through'), ('UNPAID', 'Unpaid lunch (added to the end)'), ('PAID', 'Paid lunch (on duty, included)')]
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='shift_templates')
    name = models.CharField(max_length=60)
    day_types = models.CharField(max_length=40, default=ALL_DAY_TYPES, help_text="Comma separated: WEEKDAY, SAT, SUN, HOLIDAY.")
    start_time = models.TimeField()
    paid_hours = models.DecimalField(max_digits=4, decimal_places=2, default=8)
    break_type = models.CharField(max_length=6, choices=BREAK_CHOICES, default='NONE')
    break_minutes = models.PositiveSmallIntegerField(default=0)
    break_window = models.CharField(max_length=40, blank=True, help_text="Preferred lunch window, e.g. 11:00-13:00.")
    paid_rest_minutes = models.PositiveSmallIntegerField(default=0, help_text="Short paid tea breaks: do not change paid hours.")
    pay_night = models.BooleanField(default=False)
    pay_sunday = models.BooleanField(default=False)
    pay_holiday = models.BooleanField(default=False)
    pay_weekend = models.BooleanField(default=False)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    compliance_basis = models.CharField(max_length=250, blank=True, help_text="Required when a shift over 5 hours has no meal interval: the written agreement or council rule.")
    compliance_acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['site', 'start_time']

    def __str__(self):
        return f"{self.site} {self.name} {self.start_time:%H:%M}-{self.end_time:%H:%M}"

    @property
    def end_time(self):
        from ..rostering.engine import template_end
        return template_end(self.start_time, float(self.paid_hours), self.break_type, self.break_minutes)

    @property
    def crosses_midnight(self):
        return self.end_time <= self.start_time

    @property
    def on_site_hours(self):
        from ..rostering.engine import duration_hours
        return duration_hours(self.start_time, self.end_time)

    @property
    def day_type_set(self):
        return csv_set(self.day_types)

    def compliance_notice(self):
        from ..rostering.engine import compliance_notice_for_break
        return compliance_notice_for_break(float(self.paid_hours), self.break_type)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.compliance_notice() and not self.compliance_basis.strip():
            raise ValidationError({'compliance_basis': self.compliance_notice() + " Record the basis to save."})


class OpenPOS(models.Model):
    """DR-2: how many POS are open in a shift on a day type."""
    template = models.ForeignKey(ShiftTemplate, on_delete=models.CASCADE, related_name='open_pos')
    day_type = models.CharField(max_length=8, choices=DAY_TYPE_CHOICES)
    count = models.PositiveSmallIntegerField(default=1)

    class Meta:
        unique_together = ('template', 'day_type')


class DemandRule(models.Model):
    TYPE_CHOICES = [('FIXED', 'Fixed'), ('RANGE', 'Range (minimum, target, maximum)'), ('PER_POS', 'One per open POS'), ('PER_BUILDING', 'Per building')]
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='demand_rules')
    template = models.ForeignKey(ShiftTemplate, on_delete=models.CASCADE, related_name='demand_rules')
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='demand_rules')
    day_types = models.CharField(max_length=40, default=ALL_DAY_TYPES)
    rule_type = models.CharField(max_length=12, choices=TYPE_CHOICES, default='FIXED')
    minimum = models.PositiveSmallIntegerField(default=1)
    target = models.PositiveSmallIntegerField(null=True, blank=True)
    maximum = models.PositiveSmallIntegerField(null=True, blank=True)
    per_unit = models.PositiveSmallIntegerField(default=1)
    priority = models.PositiveSmallIntegerField(default=0, help_text="Higher is filled first when there are not enough people (DR-5).")
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['site', 'template', 'post']

    def __str__(self):
        return f"{self.post} in {self.template.name}: {self.get_rule_type_display()}"


class DemandOverride(models.Model):
    """DR-4: changed demand for a date or range (month-end, promotion, event)."""
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='demand_overrides')
    start_date = models.DateField()
    end_date = models.DateField()
    template = models.ForeignKey(ShiftTemplate, on_delete=models.CASCADE, null=True, blank=True)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, null=True, blank=True)
    minimum = models.PositiveSmallIntegerField()
    target = models.PositiveSmallIntegerField(null=True, blank=True)
    maximum = models.PositiveSmallIntegerField(null=True, blank=True)
    reason = models.CharField(max_length=150, blank=True)


class RosterSettings(models.Model):
    """Off-day, rest and hours rules with their defaults (Section 6)."""
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='roster_settings')
    max_consecutive_days = models.PositiveSmallIntegerField(default=6)
    min_rest_hours = models.DecimalField(max_digits=4, decimal_places=1, default=12)
    weekly_rest_hours = models.DecimalField(max_digits=4, decimal_places=1, default=36)
    max_week_hours = models.DecimalField(max_digits=4, decimal_places=1, default=45)
    max_overtime_hours = models.DecimalField(max_digits=4, decimal_places=1, default=10)
    max_night_run = models.PositiveSmallIntegerField(default=5)
    min_off_days_per_week = models.PositiveSmallIntegerField(default=1)
    tolerance_hours = models.DecimalField(max_digits=4, decimal_places=1, default=4)
    leave_counts_toward_hours = models.BooleanField(default=True)
    leave_counts_as_off_day = models.BooleanField(default=False)
    min_notice_hours = models.PositiveSmallIntegerField(default=24, help_text="Shift change requests must be made this many hours before the shift.")
    swap_auto_approve = models.BooleanField(default=False, help_text="A swap between two eligible people is approved without a manager.")
    request_expiry_hours = models.PositiveSmallIntegerField(default=48)
    month_basis = models.CharField(max_length=10, default='CALENDAR', choices=[('CALENDAR', 'Calendar month'), ('PAY_PERIOD', 'Pay period')])
    pay_period_start_day = models.PositiveSmallIntegerField(default=26, help_text="If pay period: the day of the month a period starts (26 = 26th to 25th).")

    def engine_rules(self):
        from ..rostering.engine import Rules
        return Rules(max_consecutive_days=self.max_consecutive_days, min_rest_hours=float(self.min_rest_hours),
                     weekly_rest_hours=float(self.weekly_rest_hours), max_week_hours=float(self.max_week_hours),
                     max_overtime_hours=float(self.max_overtime_hours), max_night_run=self.max_night_run,
                     min_off_days_per_week=self.min_off_days_per_week, tolerance_hours=float(self.tolerance_hours),
                     leave_counts=self.leave_counts_toward_hours)


# ------------------------------------------------------------------ rosters and shifts
class Roster(models.Model):
    STATUS = [('DRAFT', 'Draft'), ('PUBLISHED', 'Published'), ('ARCHIVED', 'Replaced')]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='rosters')
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS, default='DRAFT')
    version = models.PositiveSmallIntegerField(default=1)
    quality_score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['-start_date', '-id']

    def __str__(self):
        return f"Roster {self.start_date:%d %b} to {self.end_date:%d %b %Y} ({self.get_status_display()})"


class RosterVersion(models.Model):
    """MR-7: every publish and every later edit keeps the earlier version."""
    roster = models.ForeignKey(Roster, on_delete=models.CASCADE, related_name='versions')
    version = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=250, blank=True)
    snapshot = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version']


class Shift(models.Model):
    """One person in one slot. employee empty = an open shift."""
    STATUS_CHOICES = [('DRAFT', 'Draft'), ('PUBLISHED', 'Published'), ('ABSENT', 'Absent'), ('CANCELLED', 'Cancelled')]
    SOURCE_CHOICES = [('GENERATED', 'Generated'), ('MANUAL', 'Manager'), ('PATTERN', 'Pattern'), ('CASUAL', 'Casual call-out'),
                      ('SWAP', 'Swap'), ('EMERGENCY', 'Emergency cover'), ('OPEN', 'Open shift')]
    roster = models.ForeignKey(Roster, on_delete=models.CASCADE, null=True, blank=True, related_name='shifts')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, null=True, blank=True, related_name='shifts')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    template = models.ForeignKey(ShiftTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='shifts')
    post = models.ForeignKey(Post, on_delete=models.SET_NULL, null=True, blank=True, related_name='shifts')
    slot_index = models.PositiveSmallIntegerField(default=0)
    required = models.BooleanField(default=True, help_text="Counts toward the minimum cover.")
    paid_hours = models.DecimalField(max_digits=5, decimal_places=2, default=8)
    night_minutes = models.PositiveSmallIntegerField(default=0)
    pinned = models.BooleanField(default=False)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='MANUAL')
    note = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    freed_from = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', help_text="Approved leave freed this slot; it returns to them if the leave is cancelled.")

    class Meta:
        ordering = ['date', 'start_time']
        indexes = [models.Index(fields=['date', 'employee']), models.Index(fields=['roster', 'date'])]

    def __str__(self):
        return f"{self.employee or 'OPEN'} {self.date} {self.start_time:%H:%M}-{self.end_time:%H:%M}"

    @property
    def start_at(self):
        return datetime.combine(self.date, self.start_time)

    @property
    def end_at(self):
        d = self.date + (timedelta(days=1) if self.end_time <= self.start_time else timedelta())
        return datetime.combine(d, self.end_time)

    @property
    def is_open(self):
        return self.employee_id is None


class Availability(models.Model):
    """CW-3: when a person can or cannot work, by weekday (and optionally a time range)."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='availability')
    weekday = models.PositiveSmallIntegerField(help_text="0 = Monday")
    available = models.BooleanField(default=True)
    from_time = models.TimeField(null=True, blank=True)
    to_time = models.TimeField(null=True, blank=True)
    note = models.CharField(max_length=150, blank=True)

    class Meta:
        unique_together = ('employee', 'weekday')
        ordering = ['weekday']


class ShiftOffer(models.Model):
    """CW-4/CW-5/SC-7: an open shift offered to a casual or to replacement candidates."""
    STATUS = [('OFFERED', 'Offered'), ('ACCEPTED', 'Accepted'), ('DECLINED', 'Declined'), ('CONFIRMED', 'Confirmed'),
              ('LOST', 'Filled by someone else'), ('EXPIRED', 'Expired')]
    KIND = [('CASUAL', 'Casual call-out'), ('EMERGENCY', 'Emergency cover')]
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name='offers')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='shift_offers')
    kind = models.CharField(max_length=10, choices=KIND, default='CASUAL')
    urgent = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=STATUS, default='OFFERED')
    sent_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    rank = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ('shift', 'employee')
        ordering = ['rank', 'sent_at']


class ShiftAbsence(models.Model):
    """SC-6: a rostered person who did not arrive or called in sick."""
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name='absences')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='shift_absences')
    reason = models.CharField(max_length=200, blank=True)
    marked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    marked_at = models.DateTimeField(auto_now_add=True)
    replacement = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    off_day_owed = models.BooleanField(default=False, help_text="SC-9: the replacement worked a required off-day, which is owed back.")


class ShiftChangeRequest(models.Model):
    KIND_CHOICES = [('SWAP', 'Swap with a colleague'), ('GIVEAWAY', 'Give the shift away'), ('CHANGE', 'Change the time'), ('OFF', 'Ask to be taken off')]
    STATUS_CHOICES = [('REQUESTED', 'Requested'), ('AWAITING_COLLEAGUE', 'Awaiting colleague'), ('AWAITING_MANAGER', 'Awaiting manager'),
                      ('APPROVED', 'Approved'), ('DECLINED', 'Declined'), ('EXPIRED', 'Expired'), ('CANCELLED', 'Cancelled')]
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True, related_name='change_requests')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='shift_requests')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    swap_with = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    swap_shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', help_text="The colleague's shift being swapped in.")
    new_start = models.TimeField(null=True, blank=True)
    new_end = models.TimeField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='REQUESTED')
    decision_note = models.TextField(blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']


class RuleOverride(models.Model):
    """OD-4: a hard rule broken on purpose by a manager, with the reason."""
    roster = models.ForeignKey(Roster, on_delete=models.CASCADE, null=True, blank=True, related_name='overrides')
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True, related_name='overrides')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    rule_code = models.CharField(max_length=30)
    detail = models.CharField(max_length=300, blank=True)
    reason = models.CharField(max_length=300)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class OffDayOwed(models.Model):
    """SC-9: an off-day worked at short notice is owed back."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='off_days_owed')
    worked_on = models.DateField()
    settled_on = models.DateField(null=True, blank=True)

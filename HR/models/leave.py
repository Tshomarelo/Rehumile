from decimal import Decimal

from django.conf import settings
from django.db import models

from ..storage import private_storage
from django.utils import timezone

from .organisation import Company
from .people import Employee


class LeaveType(models.Model):
    ACCRUAL_CHOICES = [
        ('MONTHLY', 'Accrues monthly'),
        ('ANNUAL', 'Full entitlement credited each January'),
        ('NONE', 'No accrual (balance set by adjustment)'),
    ]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='leave_types')
    name = models.CharField(max_length=80)
    code = models.CharField(max_length=20)
    is_paid = models.BooleanField(default=True)
    annual_days = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'), help_text="Days per year.")
    accrual_method = models.CharField(max_length=8, choices=ACCRUAL_CHOICES, default='MONTHLY')
    carry_over_max = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                         help_text="Most days carried into the next year; the rest expire. Leave blank for no limit.")
    allow_negative = models.BooleanField(default=False, help_text="Allow the balance to go below zero (leave taken in advance).")
    max_negative_days = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    half_days_allowed = models.BooleanField(default=True)
    min_notice_days = models.PositiveSmallIntegerField(default=0, help_text="Calendar days of notice needed before the leave starts.")
    attachment_required_over_days = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="A supporting document (for example a medical certificate) is mandatory when the request is longer than this many days.")
    colour = models.CharField(max_length=7, default='#1a3a5c')
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('company', 'code')
        ordering = ['company', 'name']

    def __str__(self):
        return self.name

    @property
    def monthly_accrual(self):
        return (self.annual_days / Decimal('12')).quantize(Decimal('0.0001'))


class LeavePolicy(models.Model):
    """A group of leave types that applies to a group of employees."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='leave_policies')
    name = models.CharField(max_length=100)
    leave_types = models.ManyToManyField(LeaveType, related_name='policies', blank=True)
    is_default = models.BooleanField(default=False, help_text="Used for employees with no policy set.")

    class Meta:
        unique_together = ('company', 'name')
        verbose_name_plural = "leave policies"
        ordering = ['company', 'name']

    def __str__(self):
        return self.name


class PublicHoliday(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='public_holidays')
    date = models.DateField()
    name = models.CharField(max_length=100)
    site = models.ForeignKey('hr.Site', on_delete=models.CASCADE, null=True, blank=True, help_text="Leave blank for all sites.")

    class Meta:
        unique_together = ('company', 'date', 'site')
        ordering = ['date']

    def __str__(self):
        return f"{self.date} {self.name}"


class BlackoutPeriod(models.Model):
    """Dates when leave cannot be taken (year-end stock take, peak season)."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='blackout_periods')
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=200)
    department = models.ForeignKey('hr.Department', on_delete=models.CASCADE, null=True, blank=True, help_text="Leave blank for everyone.")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, null=True, blank=True, help_text="Leave blank for every leave type.")

    class Meta:
        ordering = ['start_date']

    def __str__(self):
        return f"{self.start_date} to {self.end_date}: {self.reason}"


class LeaveTransaction(models.Model):
    """The ledger behind every leave balance: accruals, leave taken,
    adjustments, carry-over and expiry. A balance is the sum of its rows, so
    it can always be explained."""
    KIND_CHOICES = [
        ('ACCRUAL', 'Accrual'), ('USAGE', 'Leave taken'), ('RESTORE', 'Leave cancelled (restored)'),
        ('ADJUSTMENT', 'Manual adjustment'), ('EXPIRY', 'Expired at year end'), ('OPENING', 'Opening balance'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_transactions')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name='transactions')
    date = models.DateField(default=timezone.localdate)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    days = models.DecimalField(max_digits=7, decimal_places=4, help_text="Positive adds to the balance, negative takes from it.")
    reason = models.CharField(max_length=255, blank=True)
    request = models.ForeignKey('hr.LeaveRequest', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    period_key = models.CharField(max_length=20, blank=True, help_text="Makes a scheduled accrual run once per period, e.g. 2026-09.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']
        indexes = [models.Index(fields=['employee', 'leave_type'])]

    def __str__(self):
        return f"{self.employee} {self.leave_type} {self.days:+} ({self.kind})"


class LeaveRequest(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('DECLINED', 'Declined'),
        ('CANCELLED', 'Cancelled'), ('CANCEL_REQUESTED', 'Cancellation requested'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name='requests')
    start_date = models.DateField()
    end_date = models.DateField()
    half_day_start = models.BooleanField(default=False, help_text="Only the afternoon of the first day.")
    half_day_end = models.BooleanField(default=False, help_text="Only the morning of the last day.")
    days = models.DecimalField(max_digits=6, decimal_places=2, help_text="Working days, calculated.")
    reason = models.TextField(blank=True)
    attachment = models.FileField(upload_to='hr/leave/%Y/%m/', storage=private_storage, blank=True, null=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='PENDING')
    pending_action = models.CharField(max_length=6, default='APPLY', help_text="APPLY for a new request, CANCEL while a cancellation awaits approval.")
    captured_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                    help_text="Set when HR captured the request on the employee's behalf.")
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date', '-id']

    def __str__(self):
        return f"{self.employee} {self.leave_type} {self.start_date} to {self.end_date}"

    # ---- workflow hooks (called by HR.services.workflow) ----
    def on_workflow_approved(self, instance):
        from ..services import leave as leave_service
        leave_service.finalise_approved(self, instance)

    def on_workflow_rejected(self, instance, reason):
        from ..services import leave as leave_service
        leave_service.finalise_rejected(self, instance, reason)

    def on_workflow_withdrawn(self, instance):
        from ..services import leave as leave_service
        leave_service.finalise_withdrawn(self, instance)

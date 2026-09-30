"""Salary master data, salary advances and the sync to the reconciliation system."""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from ..fields import EncryptedDecimalField, EncryptedTextField
from .organisation import Company
from .payroll import PayPeriod
from .people import Employee
from .roster import StaffGroup


class HRSettings(models.Model):
    """Company-wide switches for pay, advances and the sync."""
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='pay_settings')
    salary_sync_enabled = models.BooleanField(default=False, help_text="Go-live switch. Until it is on, nothing in the reconciliation system is changed or locked; the first-load report shows what would change.")
    post_advances_to_reconciliation = models.BooleanField(default=False, help_text="Record advances paid and repaid in the reconciliation cash records at once.")
    sync_amount_basis = models.CharField(max_length=6, default='GROSS', choices=[('GROSS', 'Gross pay'), ('NET', 'Net pay paid out'), ('COST', 'Cost to company')])
    salaries_category = models.CharField(max_length=100, default='Salaries')
    advance_category = models.CharField(max_length=100, default='Salary advance')
    writeoff_category = models.CharField(max_length=100, default='Salary advance write-off')
    books_closed_through = models.DateField(null=True, blank=True, help_text="Finance sets this: the last date of the closed accounting period. The sync never changes closed figures; it proposes an adjustment.")
    increase_needs_senior_pct = models.DecimalField(max_digits=5, decimal_places=1, default=10, help_text="A salary increase above this percentage also needs senior management approval.")
    allow_role_overlap = models.BooleanField(default=False, help_text="Small business setting: one person may capture, approve or pay the same advance. Every overlap is recorded.")
    unpaid_approved_flag_days = models.PositiveSmallIntegerField(default=3, help_text="An approved advance not paid after this many days is flagged.")
    code_valid_minutes = models.PositiveSmallIntegerField(default=15)
    agreement_text = models.TextField(default=(
        "I ask for a salary advance of the amount shown and I agree that it is deducted from my pay as scheduled, "
        "and from my final pay if I leave before it is repaid."))

    def __str__(self):
        return f"Pay settings for {self.company}"


class SalaryRecord(models.Model):
    """One effective-dated salary. Never edited in place: a change adds a new record and closes the old one (SM-3)."""
    PAY_TYPES = [('MONTHLY', 'Monthly salary'), ('WEEKLY', 'Weekly wage'), ('HOURLY', 'Hourly rate'), ('SHIFT', 'Per-shift rate')]
    FREQUENCY = [('MONTHLY', 'Monthly'), ('FORTNIGHTLY', 'Fortnightly'), ('WEEKLY', 'Weekly')]
    STATUS = [('PENDING', 'Waiting for approval'), ('APPROVED', 'Approved'), ('REJECTED', 'Declined'), ('WITHDRAWN', 'Withdrawn')]
    SYNC = [('NA', 'Not applicable'), ('PENDING', 'Pending'), ('SYNCED', 'Synced'), ('FAILED', 'Failed'), ('UNMATCHED', 'Not matched')]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='salary_records')
    pay_type = models.CharField(max_length=8, choices=PAY_TYPES, default='MONTHLY')
    amount = EncryptedDecimalField()
    currency = models.CharField(max_length=3, default='ZAR')
    frequency = models.CharField(max_length=12, choices=FREQUENCY, default='MONTHLY')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    reason = models.CharField(max_length=250, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default='PENDING')
    captured_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    previous = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    sync_status = models.CharField(max_length=10, choices=SYNC, default='NA')
    sync_note = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date', '-id']

    def __str__(self):
        return f"{self.employee} {self.get_pay_type_display()} from {self.start_date}"

    def on_workflow_approved(self, instance):
        from ..services import salary
        salary.finalise_approved(self, instance)

    def on_workflow_rejected(self, instance, reason):
        self.status = 'REJECTED'
        self.reason = (self.reason + f" | Declined: {reason}")[:250]
        self.save(update_fields=['status', 'reason'])

    def on_workflow_withdrawn(self, instance):
        self.status = 'WITHDRAWN'
        self.save(update_fields=['status'])


class SalaryLine(models.Model):
    """A fixed allowance or deduction inside a salary (SM-2)."""
    KIND = [('ALLOWANCE', 'Allowance'), ('DEDUCTION', 'Deduction')]
    salary = models.ForeignKey(SalaryRecord, on_delete=models.CASCADE, related_name='lines')
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=KIND, default='ALLOWANCE')
    amount = EncryptedDecimalField()
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)


# ------------------------------------------------------------------ payruns
class PayrunRun(models.Model):
    """One payrun for a pay period. Locking it triggers advance recoveries and the reconciliation sync."""
    STATUS = [('OPEN', 'Open'), ('LOCKED', 'Locked')]
    pay_period = models.OneToOneField(PayPeriod, on_delete=models.PROTECT, related_name='run')
    status = models.CharField(max_length=8, choices=STATUS, default='OPEN')
    locked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payrun {self.pay_period}"


class PayrunLine(models.Model):
    run = models.ForeignKey(PayrunRun, on_delete=models.CASCADE, related_name='lines')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payrun_lines')
    gross = EncryptedDecimalField()
    other_deductions = EncryptedDecimalField(default=Decimal('0'))
    advance_recovery = EncryptedDecimalField(default=Decimal('0'))
    net = EncryptedDecimalField()
    company_cost = EncryptedDecimalField(blank=True, null=True)

    class Meta:
        unique_together = ('run', 'employee')
        ordering = ['employee__surname']


# ------------------------------------------------------------------ advances
class AdvancePolicy(models.Model):
    """Advance rules per staff group (Section 4)."""
    staff_group = models.OneToOneField(StaffGroup, on_delete=models.CASCADE, related_name='advance_policy')
    allowed = models.BooleanField(default=True)
    casual_only_against_shifts_worked = models.BooleanField(default=True)
    max_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Fixed maximum in rand. Empty = no fixed cap.")
    max_percent_of_earned = models.DecimalField(max_digits=5, decimal_places=1, default=50, help_text="Maximum as a percentage of pay earned to date this month.")
    open_advances = models.PositiveSmallIntegerField(default=1)
    min_days_between = models.PositiveSmallIntegerField(default=0)
    min_months_service = models.PositiveSmallIntegerField(default=0)
    max_unpaid_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Not eligible while a balance above this is unpaid.")
    block_on_final_warning = models.BooleanField(default=True)
    recovery_max_payruns = models.PositiveSmallIntegerField(default=1, help_text="Longest recovery period, in payruns.")
    max_recovery_percent_of_pay = models.DecimalField(max_digits=5, decimal_places=1, default=50, help_text="No payrun may recover more than this share of the person's pay.")
    tier1_limit = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Up to this amount the line manager approves; above it senior management does.")
    fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="Default none. Shown to the employee before they confirm.")

    def __str__(self):
        return f"Advance policy for {self.staff_group}"


class Advance(models.Model):
    STATUS = [('REQUESTED', 'Requested'), ('AWAITING_APPROVAL', 'Awaiting approval'), ('APPROVED', 'Approved'), ('DECLINED', 'Declined'),
              ('PAID', 'Paid'), ('RECOVERING', 'Recovering'), ('SETTLED', 'Settled'), ('WRITTEN_OFF', 'Written off'), ('CANCELLED', 'Cancelled')]
    number = models.CharField(max_length=20, unique=True, blank=True)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name='advances')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reason = models.CharField(max_length=250)
    needed_by = models.DateField(null=True, blank=True)
    recovery_payruns = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=18, choices=STATUS, default='REQUESTED')
    captured_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                    help_text="Set when a manager, HR or supervisor captured it at the counter.")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    emergency = models.BooleanField(default=False)
    emergency_reason = models.CharField(max_length=300, blank=True)
    decision_note = models.TextField(blank=True)
    final_pay_agreed = models.BooleanField(default=False, help_text="Employee agreed the balance may come off final pay (RC-6).")
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.number} {self.employee} R{self.amount}"

    def save(self, *a, **kw):
        super().save(*a, **kw)
        if not self.number:
            self.number = f"ADV-{self.pk:06d}"
            super().save(update_fields=['number'])

    def delete(self, *a, **kw):
        if self.status in ('PAID', 'RECOVERING', 'SETTLED', 'WRITTEN_OFF'):
            raise PermissionError("A paid advance cannot be deleted. Record a repayment or a write-off instead.")
        return super().delete(*a, **kw)

    @property
    def balance(self):
        total = self.ledger.aggregate(t=models.Sum('amount'))['t']
        return (total or Decimal('0')).quantize(Decimal('0.01'))

    # ---- workflow hooks
    def on_workflow_approved(self, instance):
        from ..services import advances
        advances.finalise_approved(self, instance)

    def on_workflow_rejected(self, instance, reason):
        self.status, self.decision_note = 'DECLINED', reason
        self.save(update_fields=['status', 'decision_note'])

    def on_workflow_withdrawn(self, instance):
        self.status = 'CANCELLED'
        self.save(update_fields=['status'])


class AdvanceConfirmation(models.Model):
    """The employee's own written agreement to the deduction (AD-5)."""
    METHODS = [('CODE', 'One-time code'), ('SIGNATURE', 'Signed on screen'), ('FINAL_PAY', 'Final pay deduction')]
    advance = models.ForeignKey(Advance, on_delete=models.CASCADE, related_name='confirmations')
    method = models.CharField(max_length=10, choices=METHODS)
    code_hash = models.CharField(max_length=64, blank=True)
    code_expires = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    signed_name = models.CharField(max_length=150, blank=True)
    device = models.CharField(max_length=250, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    agreement_copy = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AdvancePayment(models.Model):
    METHODS = [('CASH_TILL', 'Cash from a till'), ('PETTY_CASH', 'Petty cash'), ('TRANSFER', 'Electronic transfer'), ('WITH_PAYRUN', 'Paid with the next payrun')]
    advance = models.OneToOneField(Advance, on_delete=models.PROTECT, related_name='payment')
    method = models.CharField(max_length=12, choices=METHODS)
    shift_id = models.PositiveIntegerField(null=True, blank=True, help_text="Reconciliation shift (till) the cash came from.")
    petty_cash_id = models.PositiveIntegerField(null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=100, blank=True)
    receipt_number = models.CharField(max_length=30, blank=True)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    paid_at = models.DateTimeField(auto_now_add=True)
    recon_expense_id = models.PositiveIntegerField(null=True, blank=True, help_text="The reconciliation record this created.")
    overlap_note = models.CharField(max_length=200, blank=True, help_text="Set when a small-business setting allowed one person in two roles.")


class RecoverySchedule(models.Model):
    STATUS = [('PLANNED', 'Planned'), ('DEDUCTED', 'Deducted'), ('CARRIED', 'Carried to next payrun')]
    advance = models.ForeignKey(Advance, on_delete=models.CASCADE, related_name='schedule')
    sequence = models.PositiveSmallIntegerField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    status = models.CharField(max_length=10, choices=STATUS, default='PLANNED')
    deducted = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        ordering = ['advance', 'sequence']


class AdvanceLedger(models.Model):
    """Every movement on the balance. Positive = owed to the business, negative = reduces what is owed (RC-1)."""
    TYPES = [('PAYMENT', 'Paid out'), ('DEDUCTION', 'Payrun deduction'), ('REPAYMENT', 'Repayment'), ('WRITE_OFF', 'Write-off'), ('FEE', 'Fee')]
    advance = models.ForeignKey(Advance, on_delete=models.PROTECT, related_name='ledger')
    type = models.CharField(max_length=10, choices=TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(default=timezone.localdate)
    source = models.CharField(max_length=200, blank=True)
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    receipt_number = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ['created_at', 'id']

    def delete(self, *a, **kw):
        raise PermissionError("Ledger entries are permanent. Record a reversing entry.")


# ------------------------------------------------------------------ sync
class SyncLink(models.Model):
    """HR person matched to the reconciliation system by employee number, never guessed (SY-2)."""
    KIND = [('MATCHED', 'Matched to a reconciliation person'), ('NO_COUNTERPART', 'No reconciliation counterpart (chosen by an administrator)')]
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='sync_link')
    kind = models.CharField(max_length=15, choices=KIND, default='MATCHED')
    recon_ref = models.CharField(max_length=100, blank=True, help_text="For example the cashier's employee number in the reconciliation system.")
    matched_by = models.CharField(max_length=30, default='employee number')
    matched_at = models.DateTimeField(auto_now_add=True)


class SyncLog(models.Model):
    """Every overwrite, adjustment or failure with old and new values (SY-4)."""
    STATUS = [('OK', 'Done'), ('NOCHANGE', 'No change'), ('FAILED', 'Failed'), ('UNMATCHED', 'Not matched'), ('ADJUSTMENT', 'Adjustment proposed'), ('SKIPPED', 'Skipped')]
    kind = models.CharField(max_length=20)            # SALARIES_EXPENSE, ADVANCE_PAID, ADVANCE_REPAID, WRITE_OFF, RATE
    source_key = models.CharField(max_length=120, db_index=True)
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    target = models.CharField(max_length=60, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    old_value = models.CharField(max_length=60, blank=True)
    new_value = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=10, choices=STATUS)
    message = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def delete(self, *a, **kw):
        raise PermissionError("The sync log is permanent.")


class AdjustmentEntry(models.Model):
    """A change proposed for a closed accounting period, for a finance user to approve (SY-6)."""
    STATUS = [('PENDING', 'Waiting for finance'), ('APPROVED', 'Approved'), ('REJECTED', 'Declined')]
    source_key = models.CharField(max_length=120, db_index=True)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='+')
    period_label = models.CharField(max_length=40)
    original_date = models.DateField()
    difference = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS, default='PENDING')
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    recon_expense_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AdvanceWriteOff(models.Model):
    """RC-8: a write-off needs senior management approval and a written reason."""
    STATUS = [('PENDING', 'Waiting for approval'), ('APPROVED', 'Approved'), ('REJECTED', 'Declined'), ('WITHDRAWN', 'Withdrawn')]
    advance = models.ForeignKey(Advance, on_delete=models.PROTECT, related_name='writeoffs')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=300)
    status = models.CharField(max_length=10, choices=STATUS, default='PENDING')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    def on_workflow_approved(self, instance):
        from ..services import advances
        advances.finalise_writeoff(self, instance)

    def on_workflow_rejected(self, instance, reason):
        self.status = 'REJECTED'
        self.save(update_fields=['status'])

    def on_workflow_withdrawn(self, instance):
        self.status = 'WITHDRAWN'
        self.save(update_fields=['status'])

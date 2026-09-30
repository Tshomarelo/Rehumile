from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from .organisation import Company
from .people import ROLE_CHOICES


# --------------------------------------------------------------------- audit
class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("Audit entries cannot be edited.")

    def delete(self):
        raise PermissionError("Audit entries cannot be deleted.")

    def bulk_update(self, *args, **kwargs):
        raise PermissionError("Audit entries cannot be edited.")


class AuditLog(models.Model):
    """Append-only record of who did what, to which record, when and from
    where. No role can edit or delete an entry; viewing sensitive records is
    logged here too."""
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    username = models.CharField(max_length=150, blank=True, help_text="Kept so the entry still reads if the login is removed.")
    action = models.CharField(max_length=60, db_index=True)
    module = models.CharField(max_length=40, db_index=True)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    employee = models.ForeignKey('hr.Employee', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 help_text="The employee the entry is about, for searching.")
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    sensitive = models.BooleanField(default=False)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ['-timestamp', '-id']

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.username} {self.action} {self.object_repr}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionError("Audit entries cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit entries cannot be deleted.")


# ------------------------------------------------------------- notifications
class Notification(models.Model):
    CATEGORY_CHOICES = [
        ('APPROVAL', 'Approval needed'), ('DECISION', 'Request decided'), ('OVERDUE', 'Approval overdue'),
        ('PAYSLIP', 'Payslip / tax certificate'), ('ROSTER', 'Roster'), ('DOCUMENT', 'Documents'),
        ('CASE', 'Employee relations'), ('SYSTEM', 'System'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hr_notifications')
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default='SYSTEM')
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    url = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    emailed = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.user}: {self.title}"

    @property
    def is_read(self):
        return self.read_at is not None


# ------------------------------------------------------------------ workflow
class WorkflowDefinition(models.Model):
    """The approval chain for one kind of request. Set in admin settings, not
    in code: which roles approve in order, and how long before an unanswered
    request is reminded and then escalated."""
    KEY_CHOICES = [
        ('leave', 'Leave request'), ('change_standard', 'Profile change'), ('change_banking', 'Banking change'),
        ('payrun_input', 'Payrun input'), ('document_request', 'Document request'), ('shift_change', 'Shift change'),
        ('salary_change', 'Salary change'), ('salary_change_large', 'Large salary increase'), ('advance_small', 'Advance (manager tier)'),
        ('advance_large', 'Advance (senior tier)'), ('advance_emergency', 'Emergency advance'), ('advance_writeoff', 'Advance write-off'),
    ]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='workflows')
    key = models.CharField(max_length=30, choices=KEY_CHOICES)
    name = models.CharField(max_length=100, blank=True)
    steps = models.JSONField(default=list, help_text="Approval roles in order, e.g. [\"LINE_MANAGER\", \"HR_ADMIN\"].")
    escalation_days = models.PositiveSmallIntegerField(default=3, help_text="Working days before a reminder, then escalation to HR.")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('company', 'key')
        ordering = ['company', 'key']

    def __str__(self):
        return f"{self.company} - {self.get_key_display()}"


class WorkflowInstance(models.Model):
    STATUS_CHOICES = [('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected'), ('WITHDRAWN', 'Withdrawn')]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='+')
    key = models.CharField(max_length=30)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    subject = GenericForeignKey('content_type', 'object_id')
    submitter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    employee = models.ForeignKey('hr.Employee', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 help_text="The employee the request is for.")
    summary = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['content_type', 'object_id'])]

    def __str__(self):
        return f"{self.get_key_display_safe()}: {self.summary}"

    def get_key_display_safe(self):
        return dict(WorkflowDefinition.KEY_CHOICES).get(self.key, self.key)

    @property
    def current_step(self):
        return self.steps.filter(status='PENDING').order_by('order').first()


class ApprovalStep(models.Model):
    STATUS_CHOICES = [
        ('WAITING', 'Waiting for earlier step'), ('PENDING', 'Awaiting decision'), ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'), ('SKIPPED', 'Skipped'), ('CANCELLED', 'Cancelled'),
    ]
    instance = models.ForeignKey(WorkflowInstance, on_delete=models.CASCADE, related_name='steps')
    order = models.PositiveSmallIntegerField()
    role = models.CharField(max_length=15, choices=ROLE_CHOICES)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                    help_text="A named approver (for example the line manager). Empty means anyone holding the role.")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='WAITING')
    acted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    acted_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    escalated = models.BooleanField(default=False)

    class Meta:
        ordering = ['instance', 'order']

    def __str__(self):
        return f"{self.instance_id} step {self.order} {self.role} {self.status}"


class Delegation(models.Model):
    """A manager hands their approvals to another for a date range, for
    example while on leave."""
    delegator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='delegations_given')
    delegate = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='delegations_received')
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.delegator} -> {self.delegate} ({self.start_date} to {self.end_date})"

    def is_active_on(self, day=None):
        day = day or timezone.localdate()
        return self.start_date <= day <= self.end_date

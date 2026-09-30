from django.conf import settings
from django.db import models

from ..storage import private_storage
from .people import Employee


class Grievance(models.Model):
    STATUS_CHOICES = [('OPEN', 'Received'), ('INVESTIGATING', 'Being looked into'), ('RESOLVED', 'Resolved'), ('CLOSED', 'Closed')]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='grievances')
    subject = models.CharField(max_length=150)
    description = models.TextField()
    status = models.CharField(max_length=14, choices=STATUS_CHOICES, default='OPEN')
    outcome = models.TextField(blank=True, help_text="Shown to the employee when resolved.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.subject} ({self.employee})"


class GrievanceNote(models.Model):
    """Internal HR notes: never shown to the employee."""
    grievance = models.ForeignKey(Grievance, on_delete=models.CASCADE, related_name='notes')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class Warning(models.Model):
    LEVEL_CHOICES = [('VERBAL', 'Verbal warning'), ('WRITTEN', 'Written warning'), ('FINAL', 'Final written warning')]
    APPEAL_CHOICES = [('NONE', 'No appeal'), ('PENDING', 'Appeal lodged'), ('UPHELD', 'Warning upheld'), ('OVERTURNED', 'Warning overturned')]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='warnings')
    level = models.CharField(max_length=8, choices=LEVEL_CHOICES)
    reason = models.TextField()
    issued_on = models.DateField()
    expiry_date = models.DateField(null=True, blank=True, help_text="Usually 6 or 12 months after issue.")
    document = models.FileField(upload_to='hr/warnings/%Y/', storage=private_storage, blank=True, null=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    ack_comment = models.CharField(max_length=255, blank=True, help_text="Employee's comment when acknowledging (acknowledging is not agreeing).")
    appeal_status = models.CharField(max_length=10, choices=APPEAL_CHOICES, default='NONE')
    appeal_text = models.TextField(blank=True)
    appeal_decision = models.TextField(blank=True)
    withdrawn = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-issued_on']

    def __str__(self):
        return f"{self.get_level_display()} - {self.employee}"

    @property
    def is_live(self):
        from django.utils import timezone
        return not self.withdrawn and self.appeal_status != 'OVERTURNED' and (not self.expiry_date or self.expiry_date >= timezone.localdate())


class Hearing(models.Model):
    STATUS_CHOICES = [('INVITED', 'Invited'), ('ACKNOWLEDGED', 'Acknowledged'), ('HELD', 'Held'), ('CANCELLED', 'Cancelled')]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='hearings')
    when = models.DateTimeField()
    venue = models.CharField(max_length=150)
    purpose = models.CharField(max_length=200)
    notes_for_employee = models.TextField(blank=True, help_text="Charges, your right to representation, documents to bring.")
    status = models.CharField(max_length=13, choices=STATUS_CHOICES, default='INVITED')
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-when']

    def __str__(self):
        return f"{self.purpose} {self.when:%d %b} - {self.employee}"

from django.conf import settings
from django.db import models

from ..storage import private_storage
from .organisation import Company
from .people import Employee


class EmployeeDocument(models.Model):
    """A personal document HR files for one employee (contract, offer letter,
    certificate). Can be sent for e-signing: the employee types their name to sign."""
    CATEGORY_CHOICES = [('CONTRACT', 'Contract'), ('OFFER', 'Offer letter'), ('CERT', 'Certificate / letter'),
                        ('ID', 'Identity / permit'), ('OTHER', 'Other')]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='documents')
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default='OTHER')
    title = models.CharField(max_length=150)
    file = models.FileField(upload_to='hr/docs/%Y/', storage=private_storage)
    requires_signature = models.BooleanField(default=False)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_name = models.CharField(max_length=150, blank=True)
    signed_ip = models.GenericIPAddressField(null=True, blank=True)
    first_viewed_at = models.DateTimeField(null=True, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, default='ACTIVE')  # ACTIVE / WITHDRAWN

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.employee})"


class Policy(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='policies')
    title = models.CharField(max_length=150)
    summary = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['title']
        verbose_name_plural = 'policies'

    def __str__(self):
        return self.title

    @property
    def current(self):
        return self.versions.order_by('-version').first()


class PolicyVersion(models.Model):
    policy = models.ForeignKey(Policy, on_delete=models.CASCADE, related_name='versions')
    version = models.PositiveSmallIntegerField(default=1)
    file = models.FileField(upload_to='hr/policies/%Y/', storage=private_storage)
    effective_date = models.DateField()
    requires_ack = models.BooleanField(default=True, verbose_name='Employees must acknowledge')
    change_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version']
        unique_together = ('policy', 'version')

    def __str__(self):
        return f"{self.policy} v{self.version}"


class PolicyAcknowledgement(models.Model):
    version = models.ForeignKey(PolicyVersion, on_delete=models.CASCADE, related_name='acknowledgements')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='policy_acks')
    acknowledged_at = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        unique_together = ('version', 'employee')


class DocumentRequest(models.Model):
    """Employee asks HR for a letter (proof of employment, salary letter...).
    Approved through the 'document_request' workflow; HR then attaches the file."""
    TYPE_CHOICES = [('EMPLOYMENT', 'Proof of employment'), ('SALARY', 'Salary / income letter'),
                    ('SERVICE', 'Service certificate'), ('OTHER', 'Other')]
    STATUS_CHOICES = [('PENDING', 'Pending approval'), ('APPROVED', 'Approved - being prepared'),
                      ('READY', 'Ready'), ('REJECTED', 'Declined'), ('WITHDRAWN', 'Withdrawn')]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='document_requests')
    doc_type = models.CharField(max_length=12, choices=TYPE_CHOICES)
    note = models.CharField(max_length=255, blank=True, help_text="Who it is for, and why.")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    decision_note = models.TextField(blank=True)
    document = models.ForeignKey(EmployeeDocument, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee} {self.get_doc_type_display()}"

    def on_workflow_approved(self, instance):
        self.status = 'APPROVED'
        self.save(update_fields=['status'])

    def on_workflow_rejected(self, instance, reason):
        self.status, self.decision_note = 'REJECTED', reason
        self.save(update_fields=['status', 'decision_note'])

    def on_workflow_withdrawn(self, instance):
        self.status = 'WITHDRAWN'
        self.save(update_fields=['status'])

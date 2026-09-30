from django.conf import settings
from django.db import models
from django.utils import timezone

from ..fields import EncryptedTextField, mask
from ..storage import private_storage
from .people import Employee


class Address(models.Model):
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='address')
    street = models.CharField(max_length=200, blank=True)
    suburb = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    province = models.CharField(max_length=60, blank=True)
    postal_code = models.CharField(max_length=10, blank=True)
    country = models.CharField(max_length=60, default='South Africa')

    class Meta:
        verbose_name_plural = "addresses"

    def __str__(self):
        return ", ".join(p for p in [self.street, self.suburb, self.city, self.postal_code] if p)


class EmergencyContact(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='emergency_contacts')
    name = models.CharField(max_length=120)
    relationship = models.CharField(max_length=60)
    phone = models.CharField(max_length=30)
    alt_phone = models.CharField(max_length=30, blank=True)
    is_next_of_kin = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.relationship})"


class Dependant(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='dependants')
    name = models.CharField(max_length=120)
    relationship = models.CharField(max_length=60)
    date_of_birth = models.DateField(null=True, blank=True)
    is_beneficiary = models.BooleanField(default=False)
    beneficiary_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.relationship})"


class BankAccount(models.Model):
    """Where pay is paid. Changes need two approvers (HR then Payroll); the
    account number is encrypted at rest."""
    ACCOUNT_TYPES = [('CHEQUE', 'Cheque / current'), ('SAVINGS', 'Savings'), ('TRANSMISSION', 'Transmission')]
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='bank_account')
    bank_name = models.CharField(max_length=80)
    account_holder = models.CharField(max_length=120)
    account_number = EncryptedTextField()
    branch_code = models.CharField(max_length=12, blank=True)
    account_type = models.CharField(max_length=12, choices=ACCOUNT_TYPES, default='CHEQUE')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.bank_name} {self.masked_number}"

    @property
    def masked_number(self):
        return mask(self.account_number)


class Qualification(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='qualifications')
    title = models.CharField(max_length=150)
    institution = models.CharField(max_length=150, blank=True)
    year_obtained = models.PositiveSmallIntegerField(null=True, blank=True)
    level = models.CharField(max_length=60, blank=True)

    def __str__(self):
        return self.title


class ChangeRequest(models.Model):
    """An employee's request to change their own record. An edit never changes
    the record directly: it becomes one of these (old and new values side by
    side, with proof where needed) and is applied only once approved."""
    ACTION_CHOICES = [('UPDATE', 'Change'), ('ADD', 'Add'), ('REMOVE', 'Remove')]
    STATUS_CHOICES = [('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Declined'), ('WITHDRAWN', 'Withdrawn')]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='change_requests')
    section = models.CharField(max_length=20)
    action = models.CharField(max_length=6, choices=ACTION_CHOICES, default='UPDATE')
    target_id = models.PositiveBigIntegerField(null=True, blank=True, help_text="Which list item, for add/remove/edit of a list section.")
    old_payload = EncryptedTextField(blank=True, null=True, help_text="JSON of the current values. Encrypted at rest (may hold banking details).")
    new_payload = EncryptedTextField(blank=True, null=True, help_text="JSON of the requested values. Encrypted at rest.")
    proof = models.FileField(upload_to='hr/proof/%Y/%m/', storage=private_storage, blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee} {self.section} {self.action}"

    # ---- workflow hooks ----
    def on_workflow_approved(self, instance):
        from ..services import biographical
        biographical.apply_request(self)

    def on_workflow_rejected(self, instance, reason):
        self.status = 'REJECTED'
        self.decision_note = reason
        self.save(update_fields=['status', 'decision_note'])

    def on_workflow_withdrawn(self, instance):
        self.status = 'WITHDRAWN'
        self.save(update_fields=['status'])

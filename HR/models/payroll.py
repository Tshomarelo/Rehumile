from django.conf import settings
from django.db import models
from django.utils import timezone

from ..fields import EncryptedDecimalField
from ..storage import private_storage
from .organisation import Company
from .people import Employee


class PayPeriod(models.Model):
    FREQUENCY_CHOICES = [('MONTHLY', 'Monthly'), ('FORTNIGHTLY', 'Fortnightly'), ('WEEKLY', 'Weekly')]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='pay_periods')
    label = models.CharField(max_length=40, help_text="For example 2026-09 or September 2026.")
    frequency = models.CharField(max_length=12, choices=FREQUENCY_CHOICES, default='MONTHLY')
    start_date = models.DateField()
    end_date = models.DateField()
    pay_date = models.DateField(null=True, blank=True)
    input_cutoff = models.DateField(null=True, blank=True, help_text="Last day payrun inputs are accepted (used by Payrun Input).")
    tax_year = models.PositiveSmallIntegerField(help_text="The year the tax year ends in: 1 Mar 2025 to 28 Feb 2026 is 2026.")

    class Meta:
        unique_together = ('company', 'label')
        ordering = ['-start_date']

    def __str__(self):
        return self.label

    @staticmethod
    def tax_year_for(day):
        """South African tax year runs 1 March to end of February."""
        return day.year + 1 if day.month >= 3 else day.year


class TaxYear(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='tax_years')
    year = models.PositiveSmallIntegerField(help_text="The year the tax year ends in.")

    class Meta:
        unique_together = ('company', 'year')
        ordering = ['-year']

    def __str__(self):
        return f"{self.year - 1}/{self.year}"

    @property
    def label(self):
        return f"1 Mar {self.year - 1} - end Feb {self.year}"


class ImportBatch(models.Model):
    """One upload of payslips or tax certificates, previewed before anything
    is visible to employees."""
    KIND_CHOICES = [('PAYSLIP', 'Payslips'), ('TAXCERT', 'Tax certificates')]
    STATUS_CHOICES = [('PREVIEW', 'Preview'), ('SCHEDULED', 'Scheduled'), ('PUBLISHED', 'Published'), ('CANCELLED', 'Cancelled')]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='+')
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.PROTECT, null=True, blank=True, related_name='batches')
    tax_year = models.ForeignKey(TaxYear, on_delete=models.PROTECT, null=True, blank=True, related_name='batches')
    cert_type = models.CharField(max_length=8, blank=True, default='IRP5')
    source_file = models.FileField(upload_to='hr/batches/%Y/%m/', storage=private_storage)
    data_file = models.FileField(upload_to='hr/batches/%Y/%m/', storage=private_storage, blank=True, null=True,
                                 help_text="Optional CSV: employee_number, gross, deductions, net.")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PREVIEW')
    publish_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    summary = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        target = self.pay_period or self.tax_year
        return f"{self.get_kind_display()} {target}"


class Payslip(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'), ('PUBLISHED', 'Published'), ('WITHDRAWN', 'Withdrawn'), ('SUPERSEDED', 'Replaced by a corrected version'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, null=True, blank=True, related_name='payslips',
                                 help_text="Empty while a page could not be matched to an employee.")
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.PROTECT, related_name='payslips')
    batch = models.ForeignKey(ImportBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='payslips')
    file = models.FileField(upload_to='hr/payslips/%Y/%m/', storage=private_storage)
    version = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    gross = EncryptedDecimalField(blank=True, null=True)
    deductions = EncryptedDecimalField(blank=True, null=True)
    net = EncryptedDecimalField(blank=True, null=True)
    match_note = models.CharField(max_length=255, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    first_viewed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pay_period__start_date', 'employee__surname', '-version']

    def __str__(self):
        return f"{self.employee or 'Unmatched'} {self.pay_period} v{self.version}"


class TaxCertificate(models.Model):
    TYPE_CHOICES = [('IRP5', 'IRP5'), ('IT3A', 'IT3(a)')]
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'), ('PUBLISHED', 'Published'), ('CORRECTION', 'Correction requested'),
        ('SUPERSEDED', 'Replaced by a reissued version'), ('WITHDRAWN', 'Withdrawn'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, null=True, blank=True, related_name='tax_certificates')
    tax_year = models.ForeignKey(TaxYear, on_delete=models.PROTECT, related_name='certificates')
    cert_type = models.CharField(max_length=4, choices=TYPE_CHOICES, default='IRP5')
    batch = models.ForeignKey(ImportBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='certificates')
    file = models.FileField(upload_to='hr/tax/%Y/', storage=private_storage)
    version = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    match_note = models.CharField(max_length=255, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    first_viewed_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    download_count = models.PositiveIntegerField(default=0)
    correction_note = models.TextField(blank=True)
    correction_requested_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-tax_year__year', 'employee__surname', '-version']

    def __str__(self):
        return f"{self.employee or 'Unmatched'} {self.tax_year} {self.cert_type} v{self.version}"

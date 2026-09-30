from django.db import models

from ..storage import private_storage
from .payroll import PayPeriod
from .people import Employee


class PayrunInput(models.Model):
    """Something an employee asks to have included in a coming payrun.
    Line manager approves, then Payroll; only approved lines are exported."""
    KIND_CHOICES = [('OVERTIME', 'Overtime'), ('ALLOWANCE', 'Allowance'),
                    ('EXPENSE', 'Expense claim'), ('DEDUCTION', 'Deduction request')]
    STATUS_CHOICES = [('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Declined'), ('WITHDRAWN', 'Withdrawn')]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payrun_inputs')
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.PROTECT, related_name='inputs')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    description = models.CharField(max_length=200)
    work_date = models.DateField(null=True, blank=True, help_text="Date worked or spent.")
    hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    receipt = models.FileField(upload_to='hr/receipts/%Y/%m/', storage=private_storage, blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee} {self.get_kind_display()} {self.pay_period}"

    def on_workflow_approved(self, instance):
        self.status = 'APPROVED'
        self.save(update_fields=['status'])

    def on_workflow_rejected(self, instance, reason):
        self.status, self.decision_note = 'REJECTED', reason
        self.save(update_fields=['status', 'decision_note'])

    def on_workflow_withdrawn(self, instance):
        self.status = 'WITHDRAWN'
        self.save(update_fields=['status'])

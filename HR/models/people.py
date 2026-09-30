from datetime import date

from django.conf import settings
from django.db import models
from django.utils import timezone

from ..fields import EncryptedDecimalField, EncryptedTextField, mask
from .organisation import Company, CostCentre, Department, Position, Site

# The five HR roles. Kept as plain strings so they can be stored on
# RoleAssignment and written into a workflow definition's approval chain.
EMPLOYEE = 'EMPLOYEE'
LINE_MANAGER = 'LINE_MANAGER'
HR_ADMIN = 'HR_ADMIN'
PAYROLL_ADMIN = 'PAYROLL_ADMIN'
SUPER_ADMIN = 'SUPER_ADMIN'
SENIOR_MANAGER = 'SENIOR_MANAGER'       # approves large advances, large salary increases, write-offs
ADVANCE_PAYER = 'ADVANCE_PAYER'         # pays out advances at the counter; kept apart from salary roles (CT-2)
ROLE_CHOICES = [
    (EMPLOYEE, 'Employee'),
    (LINE_MANAGER, 'Line Manager'),
    (HR_ADMIN, 'HR Admin'),
    (PAYROLL_ADMIN, 'Payroll Admin'),
    (SUPER_ADMIN, 'Super Admin'),
    (SENIOR_MANAGER, 'Senior Management'),
    (ADVANCE_PAYER, 'Advance Payer'),
]
ADMIN_ROLES = {HR_ADMIN, PAYROLL_ADMIN, SUPER_ADMIN}


class Employee(models.Model):
    GENDER_CHOICES = [('F', 'Female'), ('M', 'Male'), ('X', 'Other / non-binary'), ('N', 'Prefer not to say')]
    RACE_CHOICES = [
        ('A', 'African'), ('C', 'Coloured'), ('I', 'Indian'), ('W', 'White'),
        ('O', 'Other'), ('N', 'Prefer not to say'),
    ]
    STATUS_CHOICES = [('ACTIVE', 'Active'), ('ON_LEAVE', 'On extended leave'), ('SUSPENDED', 'Suspended'), ('TERMINATED', 'Terminated')]
    CONTRACT_CHOICES = [('PERMANENT', 'Permanent'), ('FIXED_TERM', 'Fixed term'), ('CASUAL', 'Casual'), ('INTERN', 'Intern / learnership')]

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='employees')
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='hr_employee')
    employee_number = models.CharField(max_length=30)
    known_as = models.CharField(max_length=100)
    first_names = models.CharField(max_length=200)
    surname = models.CharField(max_length=100)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    race = models.CharField(max_length=1, choices=RACE_CHOICES, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    id_number = EncryptedTextField(blank=True, null=True, help_text="Encrypted at rest.")
    nationality = models.CharField(max_length=80, blank=True, default='South African')
    work_email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    photo = models.ImageField(upload_to='hr/photos/', blank=True, null=True)
    personal_email = models.EmailField(blank=True)
    driver_licence_code = models.CharField(max_length=10, blank=True)
    driver_licence_expiry = models.DateField(null=True, blank=True)
    permit_expiry = models.DateField(null=True, blank=True)
    medical_aid_scheme = models.CharField(max_length=100, blank=True)
    medical_aid_number = EncryptedTextField(blank=True, null=True)
    skills = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='ACTIVE')
    start_date = models.DateField(null=True, blank=True)
    termination_date = models.DateField(null=True, blank=True)
    leave_policy = models.ForeignKey('hr.LeavePolicy', on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')

    # Current job details - kept in step with the latest EmploymentRecord by
    # refresh_current(), so lists and team scoping do not need to join history.
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    position = models.ForeignKey(Position, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    cost_centre = models.ForeignKey(CostCentre, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    manager = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='direct_reports')
    contract_type = models.CharField(max_length=12, choices=CONTRACT_CHOICES, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('company', 'employee_number')
        ordering = ['surname', 'known_as']

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return f"{self.known_as} {self.surname}".strip()

    @property
    def full_name(self):
        return f"{self.first_names} {self.surname}".strip()

    @property
    def job_title(self):
        return self.position.title if self.position_id else ''

    @property
    def is_active(self):
        return self.status != 'TERMINATED'

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = date.today()
        return today.year - self.date_of_birth.year - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))

    @property
    def retirement_age(self):
        return self.company.retirement_age

    @property
    def masked_id_number(self):
        return mask(self.id_number)

    def record_on(self, on=None):
        on = on or timezone.localdate()
        return self.records.filter(effective_from__lte=on).order_by('-effective_from', '-id').first()

    def refresh_current(self):
        """Copy the latest effective EmploymentRecord onto the employee."""
        rec = self.record_on()
        if rec:
            self.department = rec.department
            self.position = rec.position
            self.site = rec.site
            self.cost_centre = rec.cost_centre
            self.manager = rec.manager
            self.contract_type = rec.contract_type
            self.save(update_fields=['department', 'position', 'site', 'cost_centre', 'manager', 'contract_type', 'updated_at'])

    def reports_chain(self):
        """This employee's managers, nearest first (guards against loops)."""
        chain, seen, mgr = [], {self.pk}, self.manager
        while mgr and mgr.pk not in seen:
            chain.append(mgr)
            seen.add(mgr.pk)
            mgr = mgr.manager
        return chain

    def all_reports(self):
        """Everyone below this employee in the reporting line."""
        result, frontier, seen = [], list(self.direct_reports.all()), {self.pk}
        while frontier:
            e = frontier.pop()
            if e.pk in seen:
                continue
            seen.add(e.pk)
            result.append(e)
            frontier.extend(e.direct_reports.all())
        return result


class EmploymentRecord(models.Model):
    """Effective-dated job, pay and manager details. A change is a new record
    with the date it takes effect, so history is kept and any past date can be
    answered."""
    REASON_CHOICES = [('HIRE', 'Hire'), ('PROMOTION', 'Promotion'), ('TRANSFER', 'Transfer'), ('PAY_CHANGE', 'Pay change'), ('OTHER', 'Other')]
    PAY_TYPE_CHOICES = [('SALARIED', 'Salaried'), ('HOURLY', 'Hourly')]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='records')
    effective_from = models.DateField()
    position = models.ForeignKey(Position, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    cost_centre = models.ForeignKey(CostCentre, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    manager = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_records')
    contract_type = models.CharField(max_length=12, choices=Employee.CONTRACT_CHOICES, blank=True)
    pay_type = models.CharField(max_length=10, choices=PAY_TYPE_CHOICES, default='SALARIED')
    salary_amount = EncryptedDecimalField(blank=True, null=True, help_text="Monthly salary or hourly rate. Encrypted at rest.")
    hours_per_week = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    reason = models.CharField(max_length=12, choices=REASON_CHOICES, default='OTHER')
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from', '-id']

    def __str__(self):
        return f"{self.employee} from {self.effective_from}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.employee.refresh_current()


class RoleAssignment(models.Model):
    """Which HR roles a login holds. A person can hold several and switches
    between the employee and admin views from the same login. Superusers are
    always Super Admin. Everyone with an Employee record is an Employee;
    Line Manager is also implied by having direct reports."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hr_roles')
    role = models.CharField(max_length=15, choices=ROLE_CHOICES)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True, help_text="Leave blank for all companies.")

    class Meta:
        unique_together = ('user', 'role', 'company')

    def __str__(self):
        return f"{self.user} - {self.get_role_display()}"

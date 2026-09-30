from django import forms
from django.contrib.auth import get_user_model

from .models import (
    ROLE_CHOICES, Company, Delegation, Employee, EmploymentRecord, LeaveType, RoleAssignment,
    WorkflowDefinition,
)
from .services import leave as leave_service

User = get_user_model()
DATE = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
MAX_UPLOAD = 10 * 1024 * 1024
ALLOWED_UPLOADS = {'.pdf', '.jpg', '.jpeg', '.png', '.doc', '.docx'}


def validate_upload(f):
    """File type and size limits for anything an employee uploads (10 MB)."""
    import os
    if f is None:
        return f
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ALLOWED_UPLOADS:
        raise forms.ValidationError("Upload a PDF, image (JPG, PNG) or Word document.")
    if f.size > MAX_UPLOAD:
        raise forms.ValidationError("The file is larger than 10 MB.")
    return f


class BootstrapMixin:
    def _style(self):
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, (forms.CheckboxInput,)):
                w.attrs.setdefault('class', 'form-check-input')
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault('class', 'form-select')
            else:
                w.attrs.setdefault('class', 'form-control')


class StyledForm(BootstrapMixin, forms.Form):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._style()


class StyledModelForm(BootstrapMixin, forms.ModelForm):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._style()


# ------------------------------------------------------------------- leave
class LeaveApplyForm(StyledForm):
    leave_type = forms.ModelChoiceField(LeaveType.objects.none())
    start_date = forms.DateField(widget=DATE)
    end_date = forms.DateField(widget=DATE)
    half_day_start = forms.BooleanField(required=False, label="Half day on the first day (afternoon only)")
    half_day_end = forms.BooleanField(required=False, label="Half day on the last day (morning only)")
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)
    attachment = forms.FileField(required=False, label="Supporting document (optional, mandatory for long sick leave)")

    def __init__(self, employee, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        if employee is not None:
            self.fields['leave_type'].queryset = leave_service.leave_types_for(employee)

    def clean_attachment(self):
        return validate_upload(self.cleaned_data.get('attachment'))

    def clean(self):
        data = super().clean()
        if data.get('start_date') and data.get('end_date') and data['end_date'] < data['start_date']:
            self.add_error('end_date', "The end date is before the start date.")
        return data


class LeaveCaptureForm(LeaveApplyForm):
    """HR captures leave for someone else, for example sick leave phoned in."""
    employee = forms.ModelChoiceField(Employee.objects.none())
    approve_now = forms.BooleanField(required=False, initial=True, label="Approve immediately")

    def __init__(self, company, *args, **kwargs):
        first = Employee.objects.filter(company=company).exclude(status='TERMINATED').first()
        super().__init__(first, *args, **kwargs)
        self.fields['employee'].queryset = Employee.objects.filter(company=company).exclude(status='TERMINATED')
        self.fields['leave_type'].queryset = LeaveType.objects.filter(company=company, is_active=True)
        self.order_fields(['employee', 'leave_type', 'start_date', 'end_date', 'half_day_start', 'half_day_end', 'reason', 'attachment', 'approve_now'])


class LeaveAdjustForm(StyledForm):
    employee = forms.ModelChoiceField(Employee.objects.none())
    leave_type = forms.ModelChoiceField(LeaveType.objects.none())
    days = forms.DecimalField(max_digits=7, decimal_places=2, help_text="Positive adds days, negative removes them.")
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}), help_text="Required. It is recorded on the ledger and in the audit log.")

    def __init__(self, company, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['employee'].queryset = Employee.objects.filter(company=company).exclude(status='TERMINATED')
        self.fields['leave_type'].queryset = LeaveType.objects.filter(company=company, is_active=True)


# --------------------------------------------------------------- employees
class EmployeeForm(StyledModelForm):
    class Meta:
        model = Employee
        fields = [
            'employee_number', 'known_as', 'first_names', 'surname', 'gender', 'race', 'date_of_birth',
            'id_number', 'nationality', 'work_email', 'phone', 'status', 'start_date', 'termination_date',
            'leave_policy', 'user',
        ]
        widgets = {'date_of_birth': DATE, 'start_date': DATE, 'termination_date': DATE}

    def __init__(self, company, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        from .models import LeavePolicy
        self.fields['leave_policy'].queryset = LeavePolicy.objects.filter(company=company)
        taken = Employee.objects.exclude(user__isnull=True)
        if self.instance.pk:
            taken = taken.exclude(pk=self.instance.pk)
        self.fields['user'].queryset = User.objects.filter(is_active=True).exclude(pk__in=taken.values('user_id'))
        self.fields['user'].help_text = "The login this person uses. Leave blank until they have one."

    def clean_employee_number(self):
        number = self.cleaned_data['employee_number']
        clash = Employee.objects.filter(company=self.company, employee_number=number).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("That employee number is already in use.")
        return number


class EmploymentRecordForm(StyledModelForm):
    class Meta:
        model = EmploymentRecord
        fields = ['effective_from', 'position', 'department', 'site', 'cost_centre', 'manager', 'contract_type',
                  'pay_type', 'salary_amount', 'hours_per_week', 'reason', 'notes']
        widgets = {'effective_from': DATE}

    def __init__(self, company, employee, *args, show_salary=True, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import CostCentre, Department, Position, Site
        self.fields['position'].queryset = Position.objects.filter(company=company)
        self.fields['department'].queryset = Department.objects.filter(company=company)
        self.fields['site'].queryset = Site.objects.filter(company=company)
        self.fields['cost_centre'].queryset = CostCentre.objects.filter(company=company)
        self.fields['manager'].queryset = Employee.objects.filter(company=company).exclude(status='TERMINATED').exclude(pk=employee.pk if employee else None)
        if not show_salary:
            del self.fields['salary_amount']


class RoleAssignmentForm(StyledModelForm):
    class Meta:
        model = RoleAssignment
        fields = ['user', 'role', 'company']

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields['user'].queryset = User.objects.filter(is_active=True).order_by('username')
        self.fields['company'].queryset = Company.objects.filter(is_active=True)


class DelegationForm(StyledModelForm):
    class Meta:
        model = Delegation
        fields = ['delegate', 'start_date', 'end_date']
        widgets = {'start_date': DATE, 'end_date': DATE}

    def __init__(self, user, *a, **kw):
        super().__init__(*a, **kw)
        self.fields['delegate'].queryset = User.objects.filter(is_active=True).exclude(pk=user.pk).order_by('username')

    def clean(self):
        data = super().clean()
        if data.get('start_date') and data.get('end_date') and data['end_date'] < data['start_date']:
            self.add_error('end_date', "The end date is before the start date.")
        return data


class WorkflowDefinitionForm(StyledModelForm):
    steps_text = forms.CharField(
        label="Approval chain", help_text="Roles in order, comma separated. Choose from: " + ", ".join(v for v, _ in ROLE_CHOICES if v != 'EMPLOYEE'))

    class Meta:
        model = WorkflowDefinition
        fields = ['key', 'name', 'escalation_days', 'is_active']

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if self.instance.pk:
            self.fields['steps_text'].initial = ", ".join(self.instance.steps)
            self.fields['key'].disabled = True

    def clean_steps_text(self):
        steps = [s.strip().upper() for s in self.cleaned_data['steps_text'].split(',') if s.strip()]
        valid = {v for v, _ in ROLE_CHOICES if v != 'EMPLOYEE'}
        bad = [s for s in steps if s not in valid]
        if bad or not steps:
            raise forms.ValidationError("Use one or more of: " + ", ".join(sorted(valid)))
        return steps

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.steps = self.cleaned_data['steps_text']
        if commit:
            obj.save()
        return obj


class PhotoForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ['photo']

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if photo and hasattr(photo, 'size') and photo.size > MAX_UPLOAD:
            raise forms.ValidationError("The photo is larger than 10 MB.")
        return photo


# --------------------------------------------------- biographical / payroll
class ChangeForm(StyledForm):
    """Built per section from HR.services.biographical.SECTIONS."""
    def __init__(self, section, *a, **kw):
        from .services.biographical import SECTIONS, FIELD_LABELS
        super().__init__(*a, **kw)
        required = ('name', 'title', 'bank_name', 'account_holder', 'account_number')
        for f in SECTIONS[section][2]:
            if f == 'date_of_birth':
                fld = forms.DateField(widget=DATE, required=False)
            elif f == 'account_type':
                from .models import BankAccount
                fld = forms.ChoiceField(choices=BankAccount.ACCOUNT_TYPES)
            elif f == 'year_obtained':
                fld = forms.IntegerField(required=False)
            else:
                fld = forms.CharField(required=f in required, max_length=200)
            fld.label = FIELD_LABELS.get(f, f)
            self.fields[f] = fld
        if SECTIONS[section][4]:
            self.fields['proof'] = forms.FileField(label='Proof (PDF or photo)', required=False)
        self._style()


class BatchForm(StyledForm):
    source_file = forms.FileField(label='PDF (one combined file) or ZIP of PDFs named by employee number')
    data_file = forms.FileField(label='Optional CSV: employee_number, gross, deductions, net', required=False)
    publish_at = forms.DateTimeField(required=False, label='Schedule for (leave empty to publish by hand)',
                                     widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'))

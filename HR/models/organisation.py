from django.conf import settings
from django.db import models


class Company(models.Model):
    """The employer. Every HR record carries a company so more can be added
    later; one is enough to start."""
    name = models.CharField(max_length=200, unique=True)
    legal_name = models.CharField(max_length=200, blank=True)
    logo = models.ImageField(upload_to='hr/company/', blank=True, null=True)
    banner = models.ImageField(upload_to='hr/company/', blank=True, null=True, help_text="Employer banner shown on 'This is me'.")
    primary_colour = models.CharField(max_length=7, default='#1a3a5c', help_text="Hex colour, for example #1a3a5c.")
    retirement_age = models.PositiveSmallIntegerField(default=65)
    work_days = models.CharField(
        max_length=20, default='0,1,2,3,4',
        help_text="Days of the week that are working days, as numbers (Monday=0 ... Sunday=6), comma separated.")
    show_team_leave_names = models.BooleanField(
        default=True, help_text="Team calendar shows who is off. When off it shows only 'unavailable'.")
    information_officer = models.CharField(max_length=200, blank=True, help_text="POPIA Information Officer.")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "companies"
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def work_day_numbers(self):
        return {int(x) for x in self.work_days.split(',') if x.strip().isdigit()}


class Site(models.Model):
    TYPE_CHOICES = [('GARAGE', 'Garage'), ('BUILDING', 'Guarded building'), ('OFFICE', 'Office'), ('OTHER', 'Other')]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='sites')
    name = models.CharField(max_length=150)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    # Roster set-up (SR-1): what kind of place this is and when it operates.
    site_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='OTHER')
    open_time = models.TimeField(null=True, blank=True, help_text="Opening time, for example 05:00.")
    close_time = models.TimeField(null=True, blank=True, help_text="Closing time, for example 21:00.")
    is_24h = models.BooleanField(default=False, help_text="Open 24 hours, every day of the year (guarded buildings).")
    open_days = models.CharField(max_length=20, default='0,1,2,3,4,5,6',
                                 help_text="Days it operates, Monday=0 ... Sunday=6, comma separated.")
    setup_minutes = models.PositiveSmallIntegerField(default=0, help_text="Minutes a shift may start before opening (set-up).")
    cashup_minutes = models.PositiveSmallIntegerField(default=0, help_text="Minutes a shift may end after closing (cash-up).")
    managers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='managed_sites', help_text="Managers who see and edit this site's roster (MR-8).")
    auto_confirm_offers = models.BooleanField(default=True, help_text="First eligible casual to accept an offered shift gets it. Off = a manager chooses.")

    @property
    def open_day_numbers(self):
        return {int(x) for x in self.open_days.split(',') if x.strip().isdigit()}

    class Meta:
        unique_together = ('company', 'name')
        ordering = ['company', 'name']

    def __str__(self):
        return self.name


class Department(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='departments')
    name = models.CharField(max_length=150)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('company', 'name')
        ordering = ['company', 'name']

    def __str__(self):
        return self.name


class Position(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='positions')
    title = models.CharField(max_length=150)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='positions')
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('company', 'title')
        ordering = ['company', 'title']

    def __str__(self):
        return self.title


class CostCentre(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='cost_centres')
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('company', 'code')
        ordering = ['company', 'code']

    def __str__(self):
        return f"{self.code} - {self.name}"

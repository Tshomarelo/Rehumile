"""
Django Models for Rehumile Portal IMS
Comprehensive database schema for Incident Management System with dual dashboards:
- Client Dashboard: Company-specific ticket management
- HQ Dashboard: System-wide administration and monitoring
"""

from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.core.validators import MinValueValidator, URLValidator
from django.utils.translation import gettext_lazy as _
import uuid
from datetime import datetime, timedelta


# ============================================================================
# ENUM CHOICES
# ============================================================================

class StatusChoices(models.TextChoices):
    """Status choices for incidents"""
    OPEN = 'open', _('Open')
    IN_PROGRESS = 'in_progress', _('In Progress')
    RESOLVED = 'resolved', _('Resolved')
    CLOSED = 'closed', _('Closed')


class PriorityChoices(models.TextChoices):
    """Priority levels for incidents"""
    LOW = 'low', _('Low')
    MEDIUM = 'medium', _('Medium')
    HIGH = 'high', _('High')
    CRITICAL = 'critical', _('Critical')


class SLATypeChoices(models.TextChoices):
    """SLA tier types"""
    BRONZE = 'bronze', _('Bronze')
    SILVER = 'silver', _('Silver')
    GOLD = 'gold', _('Gold')


class UserRoleChoices(models.TextChoices):
    """User role types for role-based access control"""
    ADMIN = 'admin', _('HQ Administrator')
    AGENT = 'agent', _('Support Agent')
    FINANCE = 'finance', _('Finance/Billing')
    CASHIER = 'cashier', _('Administrative Desk / Cashier')
    TECHNICIAN = 'technician', _('Service Technician')
    CLIENT = 'client', _('Client User')
    VIEWER = 'viewer', _('Viewer (Read-only)')


class UserStatusChoices(models.TextChoices):
    """User account status"""
    ACTIVE = 'active', _('Active')
    INACTIVE = 'inactive', _('Inactive')
    SUSPENDED = 'suspended', _('Suspended')


class CompanyStatusChoices(models.TextChoices):
    """Company account status"""
    ACTIVE = 'active', _('Active')
    INACTIVE = 'inactive', _('Inactive')
    SUSPENDED = 'suspended', _('Suspended')


class IncidentCategoryChoices(models.TextChoices):
    """Incident categories"""
    HARDWARE = 'hardware', _('Hardware')
    SOFTWARE = 'software', _('Software')
    NETWORK = 'network', _('Network')
    DATABASE = 'database', _('Database')
    SECURITY = 'security', _('Security')
    OTHER = 'other', _('Other')


class InvoiceStatusChoices(models.TextChoices):
    """Invoice billing status"""
    DRAFT = 'draft', _('Draft')
    SENT = 'sent', _('Sent')
    PAID = 'paid', _('Paid')
    OVERDUE = 'overdue', _('Overdue')
    CANCELLED = 'cancelled', _('Cancelled')


class NotificationTypeChoices(models.TextChoices):
    """Notification types for alerts"""
    SLA_WARNING = 'sla_warning', _('SLA Warning')
    SLA_BREACH = 'sla_breach', _('SLA Breach')
    NEW_INCIDENT = 'new_incident', _('New Incident')
    ASSIGNMENT = 'assignment', _('Incident Assignment')
    INVOICE = 'invoice', _('Invoice Generated')
    GENERAL = 'general', _('General')


# ============================================================================
# CORE USER & AUTHENTICATION MODELS
# ============================================================================

class Company(models.Model):
    """
    Represents client organizations in the system.
    Core entity for multi-tenancy architecture.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Basic Information
    name = models.CharField(max_length=255, unique=True, db_index=True)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True, null=True)
    
    # Contact Information
    contact_person = models.CharField(max_length=255)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=20, blank=True)
    
    # Billing Information
    billing_email = models.EmailField()
    billing_address = models.TextField(blank=True)
    billing_city = models.CharField(max_length=100, blank=True)
    billing_state = models.CharField(max_length=100, blank=True)
    billing_postal_code = models.CharField(max_length=20, blank=True)
    billing_country = models.CharField(max_length=100, blank=True)
    
    # SLA & Service Configuration
    sla_type = models.CharField(
        max_length=20,
        choices=SLATypeChoices.choices,
        default=SLATypeChoices.SILVER
    )
    
    # Account Management
    status = models.CharField(
        max_length=20,
        choices=CompanyStatusChoices.choices,
        default=CompanyStatusChoices.ACTIVE,
        db_index=True
    )
    is_deleted = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'companies'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['sla_type']),
        ]
        verbose_name_plural = 'Companies'
    
    def __str__(self):
        return self.name


class User(AbstractUser):
    """
    Custom user model extending Django's AbstractUser.
    Supports multi-tenancy with company_id foreign key.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # User Information
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    
    # Role & Permissions
    role = models.CharField(
        max_length=20,
        choices=UserRoleChoices.choices,
        default=UserRoleChoices.CLIENT,
        db_index=True
    )
    
    # Company Association (multi-tenancy)
    # HQ Admin users have company_id=NULL or special handling
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='users',
        null=True,
        blank=True,
        db_index=True
    )
    
    # Account Status
    status = models.CharField(
        max_length=20,
        choices=UserStatusChoices.choices,
        default=UserStatusChoices.ACTIVE,
        db_index=True
    )
    
    # Authentication
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Custom permissions JSON (for granular control)
    custom_permissions = models.JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'users'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['role', 'company']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.email} ({self.role})"
    
    def is_hq_admin(self):
        """Check if user is HQ administrator"""
        return self.role == UserRoleChoices.ADMIN
    
    def is_agent(self):
        """Check if user is support agent"""
        return self.role == UserRoleChoices.AGENT
    
    def is_finance(self):
        """Check if user is finance/billing"""
        return self.role == UserRoleChoices.FINANCE
    
    def is_client(self):
        """Check if user is client"""
        return self.role == UserRoleChoices.CLIENT


class UserProfile(models.Model):
    """
    Extended user profile for additional user information.
    Separated from User model to keep it clean.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    
    # Profile Information
    phone_number = models.CharField(max_length=20, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    department = models.CharField(max_length=100, blank=True)
    avatar_url = models.URLField(blank=True)
    bio = models.TextField(blank=True)
    
    # Notification Preferences
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    in_app_notifications = models.BooleanField(default=True)
    
    # Agent-specific
    is_available = models.BooleanField(default=True)
    expertise_areas = models.JSONField(default=list, blank=True)  # ['hardware', 'network']
    max_assignments = models.IntegerField(default=10)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_profiles'
    
    def __str__(self):
        return f"Profile: {self.user.email}"


# ============================================================================
# INCIDENT MANAGEMENT MODELS
# ============================================================================

class SLAConfig(models.Model):
    """
    Configuration for SLA tiers.
    Defines response and resolution times for each SLA level.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # SLA Type
    sla_type = models.CharField(
        max_length=20,
        choices=SLATypeChoices.choices,
        unique=True
    )
    
    # Response Time (in hours)
    response_time_hours = models.IntegerField(validators=[MinValueValidator(1)])
    
    # Resolution Time (in hours)
    resolution_time_hours = models.IntegerField(validators=[MinValueValidator(1)])
    
    # Availability Window
    available_24_7 = models.BooleanField(default=False)
    business_hours_start = models.TimeField(default='08:00:00', blank=True, null=True)
    business_hours_end = models.TimeField(default='17:00:00', blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'sla_configs'
        verbose_name = 'SLA Configuration'
        verbose_name_plural = 'SLA Configurations'
    
    def __str__(self):
        return f"{self.sla_type} - {self.response_time_hours}h/{self.resolution_time_hours}h"


class Incident(models.Model):
    """
    Core incident/ticket model.
    Represents support requests from clients.
    Central to the entire IMS system.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Unique Identifier
    ticket_id = models.CharField(
        max_length=20,
        unique=True,
        db_index=True
    )
    
    # Basic Information
    title = models.CharField(max_length=255, db_index=True)
    description = models.TextField()
    category = models.CharField(
        max_length=20,
        choices=IncidentCategoryChoices.choices,
        default=IncidentCategoryChoices.OTHER,
        db_index=True
    )
    
    # Multi-tenancy
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='incidents',
        db_index=True
    )
    
    # Users Involved
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='incidents_submitted',
        null=True,
        db_index=True
    )
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='incidents_assigned',
        null=True,
        blank=True,
        db_index=True
    )
    
    # Status & Priority
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.OPEN,
        db_index=True
    )
    priority = models.CharField(
        max_length=20,
        choices=PriorityChoices.choices,
        default=PriorityChoices.MEDIUM,
        db_index=True
    )
    
    # SLA Management
    sla_type = models.CharField(
        max_length=20,
        choices=SLATypeChoices.choices,
        null=True,
        blank=True
    )
    response_deadline = models.DateTimeField(null=True, blank=True, db_index=True)
    resolution_deadline = models.DateTimeField(null=True, blank=True, db_index=True)
    is_sla_breached = models.BooleanField(default=False, db_index=True)
    sla_breach_date = models.DateTimeField(null=True, blank=True)
    
    # Billing
    is_billable = models.BooleanField(default=True)
    hours_worked = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    billable_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    # Resolution
    resolution_notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    # Escalation
    is_escalated = models.BooleanField(default=False)
    escalation_reason = models.TextField(blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    escalated_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='incidents_escalated',
        null=True,
        blank=True
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'incidents'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['company', 'priority']),
            models.Index(fields=['is_sla_breached', 'resolution_deadline']),
            models.Index(fields=['assigned_to', 'status']),
        ]
    
    def __str__(self):
        return f"{self.ticket_id} - {self.title}"
    
    def calculate_sla_deadlines(self):
        """Calculate response and resolution deadlines based on SLA type"""
        if not self.sla_type:
            self.sla_type = self.company.sla_type
        
        try:
            sla_config = SLAConfig.objects.get(sla_type=self.sla_type)
            self.response_deadline = self.created_at + timedelta(hours=sla_config.response_time_hours)
            self.resolution_deadline = self.created_at + timedelta(hours=sla_config.resolution_time_hours)
        except SLAConfig.DoesNotExist:
            pass
    
    def check_sla_breach(self):
        """Check and update SLA breach status"""
        if self.status in [StatusChoices.RESOLVED, StatusChoices.CLOSED]:
            return False
        
        now = datetime.now()
        if self.resolution_deadline and now > self.resolution_deadline:
            if not self.is_sla_breached:
                self.is_sla_breached = True
                self.sla_breach_date = now
            return True
        return False


class IncidentComment(models.Model):
    """
    Comments on incidents for discussion threads.
    Supports both internal (HQ only) and client-visible comments.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Association
    incident = models.ForeignKey(
        Incident,
        on_delete=models.CASCADE,
        related_name='comments',
        db_index=True
    )
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='incident_comments',
        null=True
    )
    
    # Content
    comment_text = models.TextField()
    is_internal = models.BooleanField(
        default=False,
        help_text="Internal comments are visible to HQ/Agents only"
    )
    
    # Editing
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = 'incident_comments'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['incident', 'created_at']),
        ]
    
    def __str__(self):
        return f"Comment on {self.incident.ticket_id} by {self.author.email}"


class IncidentAttachment(models.Model):
    """
    File attachments for incidents.
    Stores file metadata and paths for attachment downloads.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Association
    incident = models.ForeignKey(
        Incident,
        on_delete=models.CASCADE,
        related_name='attachments',
        db_index=True
    )
    
    # File Information
    file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)  # S3 path, local path, etc.
    file_size = models.BigIntegerField(validators=[MinValueValidator(0)])
    file_type = models.CharField(max_length=50, blank=True)  # MIME type
    
    # Metadata
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='attachments_uploaded',
        null=True
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'incident_attachments'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.file_name} ({self.incident.ticket_id})"


class IncidentTimeline(models.Model):
    """
    Activity timeline for incidents.
    Tracks all status, priority, and assignment changes.
    Useful for audit trail and activity history.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Association
    incident = models.ForeignKey(
        Incident,
        on_delete=models.CASCADE,
        related_name='timeline',
        db_index=True
    )
    
    # Activity
    action_type = models.CharField(
        max_length=50,
        choices=[
            ('created', 'Created'),
            ('status_changed', 'Status Changed'),
            ('priority_changed', 'Priority Changed'),
            ('assigned', 'Assigned'),
            ('reassigned', 'Reassigned'),
            ('commented', 'Commented'),
            ('attachment_added', 'Attachment Added'),
            ('escalated', 'Escalated'),
            ('sla_breached', 'SLA Breached'),
        ],
        db_index=True
    )
    description = models.TextField()
    
    # Change Details (JSON for flexibility)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    
    # User
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='timeline_activities',
        null=True
    )
    
    # Timestamp
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = 'incident_timelines'
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.incident.ticket_id} - {self.action_type}"


class SLABreach(models.Model):
    """
    Tracks SLA breaches for reporting and analytics.
    Separate model for easier querying and analysis.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Association
    incident = models.ForeignKey(
        Incident,
        on_delete=models.CASCADE,
        related_name='sla_breaches',
        db_index=True
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='sla_breaches',
        db_index=True
    )
    
    # Breach Information
    breach_type = models.CharField(
        max_length=50,
        choices=[
            ('response', 'Response Time'),
            ('resolution', 'Resolution Time'),
        ]
    )
    breached_at = models.DateTimeField(db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    time_over = models.IntegerField(help_text="Minutes over deadline")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'sla_breaches'
        ordering = ['-breached_at']
        indexes = [
            models.Index(fields=['company', 'breached_at']),
        ]
    
    def __str__(self):
        return f"SLA Breach: {self.incident.ticket_id} - {self.breach_type}"


# ============================================================================
# BILLING & INVOICE MODELS
# ============================================================================

class Invoice(models.Model):
    """
    Invoice model for billing clients.
    Aggregates incident data for a billing period.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Invoice Identifier
    invoice_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True
    )
    
    # Association
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='invoices',
        db_index=True,
        null=True,
        blank=True,
    )
    incident = models.ForeignKey(
        'Incident',
        on_delete=models.SET_NULL,
        related_name='invoices',
        null=True,
        blank=True,
        db_index=True
    )

    # Billing Period
    billing_period_start = models.DateField(db_index=True)
    billing_period_end = models.DateField(db_index=True)
    
    # Financial Details
    subtotal = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    total_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    
    # Incident Summary
    ticket_count = models.IntegerField(validators=[MinValueValidator(0)])
    hours_worked = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    
    # Status & Payment
    status = models.CharField(
        max_length=20,
        choices=InvoiceStatusChoices.choices,
        default=InvoiceStatusChoices.DRAFT,
        db_index=True
    )
    
    # Invoice type — classifies revenue stream for intelligence dashboard
    INVOICE_TYPE_CHOICES = [
        ('wifi', 'WiFi Subscription'),
        ('sla', 'SLA Monthly Retainer'),
        ('callout', 'SLA Call-Out'),
        ('adhoc', 'Ad-Hoc / Project'),
        ('subscription', 'Monthly Services (combined)'),
    ]
    invoice_type = models.CharField(max_length=20, choices=INVOICE_TYPE_CHOICES, default='adhoc', db_index=True)

    # Subscriber/contract references (set when invoice_type is wifi/sla/callout)
    wifi_subscriber = models.ForeignKey(
        'WifiSubscriber', null=True, blank=True, on_delete=models.SET_NULL, related_name='invoices',
    )
    sla_contract = models.ForeignKey(
        'SLAContract', null=True, blank=True, on_delete=models.SET_NULL, related_name='invoices',
    )
    # Axxess wholesale cost at time of invoice — locked so history is accurate even if rate changes
    wholesale_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Who is billed when there is no registered Company (direct-pay client)
    bill_to_name = models.CharField(max_length=255, blank=True)

    # Description (short human-readable label — used in print/email)
    description = models.CharField(max_length=500, blank=True)

    # Notes
    notes = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    payment_date = models.DateField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'invoices'
        ordering = ['-billing_period_end', '-created_at']
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['billing_period_start', 'billing_period_end']),
        ]
    
    def __str__(self):
        return f"INV-{self.invoice_number} ({self.company.name if self.company else 'No company'})"

    def save(self, *args, **kwargs):
        """Stamp the issue/payment dates the finance reports rely on.

        Several code paths (cashier, PayFast ITN, admin edit) flip `status`
        with save(update_fields=['status']); without this, the moment money
        arrived would never be recorded and revenue could not be placed in
        the right week/month.
        """
        from django.utils import timezone
        touched = set()
        if self.status in ('sent', 'paid', 'overdue') and not self.sent_at:
            self.sent_at = timezone.now()
            touched.add('sent_at')
        if self.status == 'paid' and not self.payment_date:
            self.payment_date = timezone.localdate()
            touched.add('payment_date')
        update_fields = kwargs.get('update_fields')
        if touched and update_fields is not None:
            kwargs['update_fields'] = set(update_fields) | touched
        super().save(*args, **kwargs)


class InvoiceItem(models.Model):
    """
    Line items for invoices.
    Each item represents billable work (incident hours, flat fee, etc.)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Association
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='items',
        db_index=True
    )
    incident = models.ForeignKey(
        Incident,
        on_delete=models.SET_NULL,
        related_name='invoice_items',
        null=True,
        blank=True
    )
    
    # Item Details
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    
    # Set on lines created from recurring services (subscriptions): lets reports split
    # revenue/cost by service and lets the billing run know what has been billed.
    service_type = models.CharField(max_length=20, blank=True)
    site_name = models.CharField(max_length=200, blank=True, help_text='Branch this line is for (shown as a heading on the invoice)')
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    subscription = models.ForeignKey(
        'Subscription', null=True, blank=True, on_delete=models.SET_NULL, related_name='invoice_items',
    )

    # Type of charge
    item_type = models.CharField(
        max_length=50,
        choices=[
            ('incident', 'Incident'),
            ('service', 'Service'),
            ('support', 'Support Hours'),
            ('other', 'Other'),
        ],
        default='incident'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'invoice_items'
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.description} - ${self.amount}"


# ============================================================================
# NOTIFICATION MODELS
# ============================================================================

class Notification(models.Model):
    """
    System notifications for users.
    Alerts about incidents, SLA breaches, assignments, etc.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # User Association
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
        db_index=True
    )
    
    # Content
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationTypeChoices.choices,
        db_index=True
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    
    # Related Objects
    incident = models.ForeignKey(
        Incident,
        on_delete=models.SET_NULL,
        related_name='notifications',
        null=True,
        blank=True
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.SET_NULL,
        related_name='notifications',
        null=True,
        blank=True
    )
    
    # Status
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata (JSON for flexibility)
    metadata = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.notification_type} - {self.user.email}"


# ============================================================================
# AUDIT & LOGGING MODELS
# ============================================================================

class AuditLog(models.Model):
    """
    Comprehensive audit trail for all system changes.
    Tracks who did what, when, and what changed.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # User
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='audit_logs',
        null=True
    )
    
    # Action Details
    action = models.CharField(max_length=50)
    model_name = models.CharField(max_length=50)
    object_id = models.CharField(max_length=50)
    
    # Changes
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    
    # Request Info
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Timestamp
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = 'audit_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['model_name', 'object_id']),
        ]
    
    def __str__(self):
        return f"{self.action} - {self.model_name} ({self.object_id})"


# ============================================================================
# DASHBOARD & ANALYTICS MODELS
# ============================================================================

class DashboardMetric(models.Model):
    """
    Pre-calculated metrics for dashboard performance.
    Updates daily to improve query performance.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Metric Details
    metric_name = models.CharField(max_length=100, db_index=True)
    metric_value = models.JSONField()
    
    # Scope
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='metrics',
        null=True,
        blank=True
    )
    
    # Date
    metric_date = models.DateField(db_index=True)
    
    class Meta:
        db_table = 'dashboard_metrics'
        unique_together = ['metric_name', 'company', 'metric_date']
        ordering = ['-metric_date']
    
    def __str__(self):
        return f"{self.metric_name} - {self.metric_date}"


class CompanyBillingInfo(models.Model):
    """
    Extended billing information for companies.
    Separated from Company model for flexibility.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Association
    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name='billing_info'
    )
    
    # Billing Terms
    billing_frequency = models.CharField(
        max_length=20,
        choices=[
            ('monthly', 'Monthly'),
            ('quarterly', 'Quarterly'),
            ('annual', 'Annual'),
        ],
        default='monthly'
    )
    
    # Rates
    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    incident_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )
    
    # Tax
    tax_id = models.CharField(max_length=50, blank=True)
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0
    )
    
    # Payment Terms
    payment_terms_days = models.IntegerField(default=30)
    accepted_payment_methods = models.JSONField(default=list)
    
    # Credit
    credit_limit = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True
    )
    current_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'company_billing_info'
    
    def __str__(self):
        return f"Billing Info: {self.company.name}"


# ============================================================================
# WORKSHOP / POS MODELS
# ============================================================================

class JobCardStatusChoices(models.TextChoices):
    LOGGED = 'logged', _('Logged')
    IN_PROGRESS = 'in_progress', _('In Progress')
    AWAITING_PARTS = 'awaiting_parts', _('Awaiting Parts')
    READY = 'ready', _('Ready for Collection')
    PAID_RELEASED = 'paid_released', _('Paid & Released')
    CANCELLED = 'cancelled', _('Cancelled')


class JobCard(models.Model):
    """Hardware repair job cards with enforced release guard."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_number = models.CharField(max_length=20, unique=True, db_index=True)

    # Customer
    customer_name = models.CharField(max_length=255)
    customer_phone = models.CharField(max_length=20, blank=True)
    customer_email = models.EmailField(blank=True)
    company = models.ForeignKey(
        Company, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='job_cards',
    )

    # Device
    device_type = models.CharField(max_length=100)
    device_brand = models.CharField(max_length=100, blank=True)
    device_model = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, db_index=True)

    # Condition & diagnosis
    physical_condition = models.TextField()
    initial_diagnosis = models.TextField()
    final_diagnosis = models.TextField(blank=True)
    technician_notes = models.TextField(blank=True)

    # Status machine
    status = models.CharField(
        max_length=20, choices=JobCardStatusChoices.choices,
        default=JobCardStatusChoices.LOGGED, db_index=True,
    )

    # Linked invoice — required before status can be set to paid_released
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='job_cards',
    )

    # Staff
    technician = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='job_cards_assigned', db_index=True,
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='job_cards_created',
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'job_cards'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'created_at'])]

    def __str__(self):
        return f"{self.job_number} — {self.customer_name}"


class InventoryItemTypeChoices(models.TextChoices):
    TOOL = 'tool', _('Lab Tool / Asset')
    CONSUMABLE = 'consumable', _('Consumable Stock')


class InventoryItem(models.Model):
    """Lab tools (assets) and consumable stock items."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item_type = models.CharField(
        max_length=20, choices=InventoryItemTypeChoices.choices,
        default=InventoryItemTypeChoices.CONSUMABLE,
    )
    name = models.CharField(max_length=255, db_index=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, blank=True, db_index=True)

    # Stock tracking (mainly for consumables)
    quantity_on_hand = models.IntegerField(default=0)
    reorder_level = models.IntegerField(default=5)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])

    # Asset-specific
    purchase_date = models.DateField(null=True, blank=True)
    deployment_status = models.CharField(
        max_length=20,
        choices=[('active', 'Active'), ('inactive', 'Inactive'), ('maintenance', 'Under Maintenance')],
        default='active',
    )

    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory_items'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_item_type_display()})"

    @property
    def is_low_stock(self):
        return self.item_type == InventoryItemTypeChoices.CONSUMABLE and self.quantity_on_hand <= self.reorder_level


class StockTransaction(models.Model):
    """Immutable ledger of all stock movements."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(
        max_length=20,
        choices=[
            ('in', 'Stock In'),
            ('out', 'Stock Out'),
            ('adjustment', 'Manual Adjustment'),
            ('cycle_count', 'Cycle Count'),
        ],
    )
    quantity = models.IntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Reference must be active job card or invoice number for stock-out
    reference = models.CharField(max_length=100, blank=True)
    job_card = models.ForeignKey(
        JobCard, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_transactions',
    )
    performed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='stock_transactions',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'stock_transactions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transaction_type} {self.quantity}x {self.item.name}"


class CashFlowStreamChoices(models.TextChoices):
    OCF = 'ocf', _('Operating Cash Flow')
    ICF = 'icf', _('Investing Cash Flow')
    FCF = 'fcf', _('Financing Cash Flow')


class ShiftLog(models.Model):
    """Daily cash register open/close protocol."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date = models.DateField(unique=True, db_index=True)

    # Morning open
    opened_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='shifts_opened',
    )
    opening_float = models.DecimalField(max_digits=10, decimal_places=2)
    opened_at = models.DateTimeField(null=True, blank=True)

    # Evening close
    closed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='shifts_closed',
    )
    physical_cash_total = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    card_total = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    eft_total = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    system_total = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    variance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_closed = models.BooleanField(default=False)

    class Meta:
        db_table = 'shift_logs'
        ordering = ['-date']

    def __str__(self):
        return f"Shift {self.date} ({'Closed' if self.is_closed else 'Open'})"


class CashTransaction(models.Model):
    """Individual payment transactions categorised by cash-flow stream."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shift = models.ForeignKey(
        ShiftLog, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transactions',
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cash_transactions',
    )
    job_card = models.ForeignKey(
        JobCard, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cash_transactions',
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(
        max_length=20,
        choices=[('cash', 'Cash'), ('card', 'Card'), ('eft', 'EFT / Transfer')],
    )
    cash_flow_stream = models.CharField(
        max_length=10, choices=CashFlowStreamChoices.choices,
        default=CashFlowStreamChoices.OCF, db_index=True,
    )
    transaction_category = models.CharField(
        max_length=20,
        choices=[
            ('sale', 'Sale'),
            ('capital_injection', 'Owner Capital Injection'),
            ('owner_drawing', "Owner's Drawing"),
            ('other', 'Other'),
        ],
        default='sale',
    )
    description = models.CharField(max_length=255)
    performed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='cash_transactions',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'cash_transactions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.payment_method} R{self.amount} ({self.cash_flow_stream})"


class PurchaseSlip(models.Model):
    """Supplier purchase slip upload for expense tracking and ICF reconciliation."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier_name = models.CharField(max_length=255)
    reference_number = models.CharField(max_length=100, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    cash_flow_stream = models.CharField(
        max_length=10, choices=CashFlowStreamChoices.choices,
        default=CashFlowStreamChoices.ICF,
    )
    slip_image_path = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='purchase_slips',
    )
    purchase_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'purchase_slips'
        ordering = ['-purchase_date']

    def __str__(self):
        return f"{self.supplier_name} R{self.amount} ({self.purchase_date})"


# ============================================================================
# DOUBLE-ENTRY ACCOUNTING ENGINE — Chart of Accounts, General Ledger, Expenses
# ============================================================================

class AccountTypeChoices(models.TextChoices):
    ASSET = 'asset', _('Asset')
    LIABILITY = 'liability', _('Liability')
    EQUITY = 'equity', _('Equity')
    REVENUE = 'revenue', _('Revenue')
    EXPENSE = 'expense', _('Expense')


class Account(models.Model):
    """
    Chart of Accounts. `system_key` is the stable, machine-readable handle
    that all auto-posting logic looks up by — never look up an Account by
    name/code from code, since those are user-editable display fields.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=10, unique=True)
    system_key = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    account_type = models.CharField(max_length=10, choices=AccountTypeChoices.choices)
    account_subtype = models.CharField(max_length=30, blank=True)
    normal_balance = models.CharField(
        max_length=6, choices=[('debit', 'Debit'), ('credit', 'Credit')],
    )
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounts'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} — {self.name}"


class LedgerTransaction(models.Model):
    """One balanced journal entry (header). Immutable once created — to
    correct a mistake, post a reversing entry via `reverses`, never edit."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction_date = models.DateField(db_index=True)
    description = models.CharField(max_length=255)
    source_model = models.CharField(max_length=50)
    source_id = models.CharField(max_length=50)
    cash_flow_stream = models.CharField(
        max_length=10, choices=CashFlowStreamChoices.choices, null=True, blank=True,
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ledger_transactions',
    )
    reverses = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reversed_by',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ledger_transactions'
        ordering = ['-transaction_date', '-created_at']
        indexes = [
            models.Index(fields=['source_model', 'source_id']),
            models.Index(fields=['transaction_date']),
        ]

    def __str__(self):
        return f"{self.transaction_date} — {self.description}"


class LedgerEntry(models.Model):
    """One debit or credit line within a LedgerTransaction."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.ForeignKey(
        LedgerTransaction, on_delete=models.CASCADE, related_name='entries',
    )
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name='ledger_entries',
    )
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    memo = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'ledger_entries'
        indexes = [models.Index(fields=['account'])]

    def __str__(self):
        return f"{self.account.system_key} Dr{self.debit}/Cr{self.credit}"


class ExpenseCategory(models.Model):
    """
    User-managed expense category (Rent, Fuel, Stock purchases, ...).
    Each category is wired to a Chart-of-Accounts account so picking a
    category on the expense form automatically decides which ledger account,
    cost type and cash-flow stream the expense posts to.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(
        max_length=12,
        choices=[('cogs', 'Cost of Goods Sold'), ('operating', 'Operating Expense'), ('capital', 'Capital / Asset Purchase')],
        default='operating',
    )
    account = models.ForeignKey('Account', on_delete=models.PROTECT, related_name='expense_categories')
    default_cash_flow_stream = models.CharField(
        max_length=10, choices=CashFlowStreamChoices.choices, default=CashFlowStreamChoices.OCF,
    )
    monthly_budget = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Optional. 0 = no budget. Shown against actual spend on the Expenses page.',
    )
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'expense_categories'
        ordering = ['display_order', 'name']
        verbose_name_plural = 'expense categories'

    def __str__(self):
        return self.name


class Expense(models.Model):
    """
    Canonical money-out record — replaces the informal 'PurchaseSlip as
    expense' pattern. Optionally wraps a PurchaseSlip when the expense also
    needs to feed the SARS VAT201 input-tax-claim pipeline.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(
        max_length=12,
        choices=[('cogs', 'Cost of Goods Sold'), ('operating', 'Operating Expense'), ('capital', 'Capital / Asset Purchase')],
    )
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='expenses')
    expense_category = models.ForeignKey(
        ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses',
    )
    # Optional link to the quotation/job this cost was incurred for — lets the
    # quotation show quoted-vs-actual cost and real margin.
    quotation = models.ForeignKey(
        'Quotation', on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    vendor = models.CharField(max_length=255)
    description = models.CharField(max_length=500, blank=True)
    expense_date = models.DateField()
    cash_flow_stream = models.CharField(
        max_length=10, choices=CashFlowStreamChoices.choices,
        default=CashFlowStreamChoices.OCF,
    )
    is_recurring = models.BooleanField(default=False)
    recurring_frequency = models.CharField(
        max_length=10,
        choices=[('weekly', 'Weekly'), ('monthly', 'Monthly'), ('quarterly', 'Quarterly'), ('annual', 'Annual')],
        blank=True,
    )
    payment_status = models.CharField(
        max_length=10, choices=[('paid', 'Paid'), ('unpaid', 'Unpaid / Payable')], default='paid',
    )
    cash_transaction = models.ForeignKey(
        CashTransaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses',
    )
    purchase_slip = models.OneToOneField(
        PurchaseSlip, on_delete=models.SET_NULL, null=True, blank=True, related_name='expense',
    )
    receipt_image_path = models.CharField(max_length=500, blank=True)
    recorded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='expenses_recorded',
    )
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses_approved',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'expenses'
        ordering = ['-expense_date']

    def __str__(self):
        return f"{self.vendor} R{self.amount} ({self.expense_date})"


class QuotationStatus(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    SENT = 'sent', _('Sent')
    ACCEPTED = 'accepted', _('Accepted')
    DECLINED = 'declined', _('Declined')
    EXPIRED = 'expired', _('Expired')
    INVOICED = 'invoiced', _('Invoiced')


class Quotation(models.Model):
    """
    Customer quotation. Line items are priced from the website service
    catalogue (ServicePrice) and can carry an expected unit cost + cost
    category, which links the quote to the expense system: expenses tagged to
    the quotation are compared with the estimate to show the real margin.
    Accepting a quote converts it to an Invoice.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quote_number = models.CharField(max_length=30, unique=True, db_index=True)
    company = models.ForeignKey(
        Company, on_delete=models.SET_NULL, null=True, blank=True, related_name='quotations',
    )
    client_name = models.CharField(max_length=200)
    client_email = models.EmailField(blank=True)
    client_phone = models.CharField(max_length=50, blank=True)
    title = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=QuotationStatus.choices, default='draft', db_index=True)
    issue_date = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='Percent, e.g. 15')
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    terms = models.TextField(blank=True)
    invoice = models.OneToOneField(
        'Invoice', on_delete=models.SET_NULL, null=True, blank=True, related_name='source_quotation',
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='quotations_created',
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    # Online acceptance: the client opens /quote/<public_token>/ — no login needed.
    public_token = models.CharField(max_length=64, unique=True, null=True, blank=True, db_index=True)
    first_viewed_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    accepted_by_name = models.CharField(max_length=200, blank=True)
    decision_note = models.TextField(blank=True)
    decision_ip = models.GenericIPAddressField(null=True, blank=True)
    decided_online = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'quotations'
        ordering = ['-issue_date', '-created_at']

    def __str__(self):
        return f"{self.quote_number} — {self.client_name}"

    def ensure_public_token(self, regenerate=False):
        """The unguessable part of the client's accept link (192 bits of randomness)."""
        import secrets
        if regenerate or not self.public_token:
            self.public_token = secrets.token_urlsafe(24)
            self.save(update_fields=['public_token', 'updated_at'])
        return self.public_token

    def recalculate(self):
        """Recompute subtotal / VAT / total / estimated cost from line items."""
        from decimal import Decimal, ROUND_HALF_UP
        cent = Decimal('0.01')
        items = list(self.items.all())
        subtotal = sum((i.line_total for i in items), Decimal('0'))
        rate = Decimal(self.vat_rate or 0)
        tax = (subtotal * rate / Decimal('100')).quantize(cent, ROUND_HALF_UP)
        self.subtotal = subtotal.quantize(cent, ROUND_HALF_UP)
        self.tax_amount = tax
        self.total_amount = self.subtotal + tax
        self.estimated_cost = sum((i.line_cost for i in items), Decimal('0')).quantize(cent, ROUND_HALF_UP)
        self.save(update_fields=['subtotal', 'tax_amount', 'total_amount', 'estimated_cost', 'updated_at'])


class QuotationItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name='items')
    service_price = models.ForeignKey(
        'ServicePrice', on_delete=models.SET_NULL, null=True, blank=True, related_name='quotation_items',
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Expected cost to Rehumile per unit (parts, wholesale, labour) — internal only.',
    )
    cost_category = models.ForeignKey(
        ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='quotation_items',
    )
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'quotation_items'
        ordering = ['display_order', 'id']

    @property
    def line_total(self):
        return (self.quantity or 0) * (self.unit_price or 0)

    @property
    def line_cost(self):
        return (self.quantity or 0) * (self.unit_cost or 0)


# ============================================================================
# RADIO/PRESENTER MODELS
# ============================================================================

class Presenter(models.Model):
    name = models.CharField(max_length=200)
    profile_picture = models.ImageField(upload_to='presenters/')
    bio = models.TextField()

    def __str__(self):
        return self.name


class Show(models.Model):
    title = models.CharField(max_length=200)
    lead_presenter = models.ForeignKey(Presenter, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return self.title


class Schedule(models.Model):
    show = models.ForeignKey(Show, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_live = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.show.title} - {self.start_time}"


# ============================================================================
# SARS COMPLIANCE STAGING ENGINE
# ============================================================================

class CompliancePeriodStatus(models.TextChoices):
    ACTIVE = 'active', _('Active (Collecting)')
    STAGING = 'staging', _('Staging (Under Review)')
    FINALIZED = 'finalized', _('Finalized / Locked')


class CompliancePeriod(models.Model):
    """Monthly VAT/PAYE compliance period — state machine: active→staging→finalized."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    period_label = models.CharField(max_length=7, unique=True)  # "2026-06"
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=CompliancePeriodStatus.choices, default='active')
    # VAT201 locked aggregates
    field1_standard_rated_sales = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    field4_output_tax = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    field14_capital_goods_input = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    field15_non_capital_input = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_vat_liability = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # EMP201 aggregates
    total_paye = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_uif_employee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_uif_employer = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Audit
    audit_flags = models.JSONField(default=list, blank=True)
    audit_ready = models.BooleanField(default=False)
    audit_zip_path = models.CharField(max_length=500, blank=True)
    finalized_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='finalized_periods',
    )
    finalized_at = models.DateTimeField(null=True, blank=True)
    staged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'compliance_periods'
        ordering = ['-period_start']

    def __str__(self):
        return f"Period {self.period_label} [{self.status}]"


class OCRStatus(models.TextChoices):
    PENDING = 'pending', _('Pending Review')
    VALID = 'valid', _('Valid')
    INVALID = 'invalid', _('Incomplete / Audit Risk')
    MANUAL = 'manual', _('Manually Verified')


class SupplierSlipOCR(models.Model):
    """OCR-validated supplier slip for VAT input tax claims (linked to PurchaseSlip)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_slip = models.OneToOneField(
        PurchaseSlip, on_delete=models.CASCADE, related_name='ocr_record',
    )
    compliance_period = models.ForeignKey(
        CompliancePeriod, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='supplier_slips',
    )
    supplier_vat_number = models.CharField(max_length=15, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stated_vat_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_capital_goods = models.BooleanField(default=False)  # True→Field14, False→Field15
    ocr_status = models.CharField(max_length=20, choices=OCRStatus.choices, default='pending')
    ocr_flags = models.TextField(blank=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    validated_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='validated_slips',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'supplier_slip_ocr'
        ordering = ['-created_at']

    def validate_vat(self):
        """Run VAT number and tax amount validation."""
        flags = []
        vat = self.supplier_vat_number.replace(' ', '')
        if not vat or not vat.isdigit() or len(vat) != 10:
            flags.append('Supplier VAT number is not a valid 10-digit SA VAT number.')
        gross = float(self.gross_amount)
        stated = float(self.stated_vat_amount)
        if gross > 0:
            calc_vat = round(gross * 15 / 115, 2)
            if abs(calc_vat - stated) > 0.10:
                flags.append(
                    f'Stated VAT R{stated:.2f} does not match calculated R{calc_vat:.2f} (15/115 rule).'
                )
        if flags:
            self.ocr_status = OCRStatus.INVALID
            self.ocr_flags = '\n'.join(flags)
        else:
            self.ocr_status = OCRStatus.VALID
            self.ocr_flags = ''
        return flags


# ============================================================================
# HR & PAYROLL ENGINE
# ============================================================================

class EmploymentType(models.TextChoices):
    FULL_TIME = 'full_time', _('Full-Time Permanent')
    PART_TIME = 'part_time', _('Part-Time')
    CONTRACT = 'contract', _('Fixed-Term Contract')
    HOURLY = 'hourly', _('Hourly / Casual')


class Employee(models.Model):
    """Digital employee file — POPIA-sensitive partition."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee_number = models.CharField(max_length=20, unique=True)
    # POPIA-sensitive fields
    id_number = models.CharField(max_length=13, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    tax_reference_number = models.CharField(max_length=20, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_number = models.CharField(max_length=30, blank=True)
    bank_branch_code = models.CharField(max_length=10, blank=True)
    physical_address = models.TextField(blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    next_of_kin_name = models.CharField(max_length=200, blank=True)
    next_of_kin_contact = models.CharField(max_length=20, blank=True)
    # Job details
    employment_type = models.CharField(max_length=20, choices=EmploymentType.choices, default='full_time')
    job_title = models.CharField(max_length=100, blank=True)
    gross_monthly_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    scheduled_hours_per_week = models.DecimalField(max_digits=5, decimal_places=2, default=40)
    monthly_allowance = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Fixed taxable allowance paid every month (transport, phone, ...).',
    )
    monthly_other_deduction = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Fixed after-tax deduction every month (staff loan repayment, garnishee, ...).',
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    linked_user = models.OneToOneField(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='employee_record',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'employees'
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.employee_number} — {self.first_name} {self.last_name}"


class LeaveTypeChoices(models.TextChoices):
    ANNUAL = 'annual', _('Annual Leave')
    SICK = 'sick', _('Sick Leave')
    FAMILY = 'family', _('Family Responsibility Leave')
    MATERNITY = 'maternity', _('Maternity / Paternity Leave')
    UNPAID = 'unpaid', _('Unpaid Leave')


class LeaveBalance(models.Model):
    """BCEA-compliant leave balance per employee per category."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_balances')
    leave_type = models.CharField(max_length=20, choices=LeaveTypeChoices.choices)
    total_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    used_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    cycle_start = models.DateField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'leave_balances'
        unique_together = ['employee', 'leave_type', 'cycle_start']

    @property
    def available_days(self):
        return max(self.total_days - self.used_days, 0)


class LeaveRequestStatus(models.TextChoices):
    PENDING = 'pending', _('Pending Approval')
    APPROVED = 'approved', _('Approved')
    REJECTED = 'rejected', _('Rejected')
    CANCELLED = 'cancelled', _('Cancelled')


class LeaveRequest(models.Model):
    """Employee leave application with manager approval workflow."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.CharField(max_length=20, choices=LeaveTypeChoices.choices)
    start_date = models.DateField()
    end_date = models.DateField()
    days_requested = models.DecimalField(max_digits=5, decimal_places=2)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=LeaveRequestStatus.choices, default='pending')
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='reviewed_leave_requests',
    )
    review_note = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'leave_requests'
        ordering = ['-created_at']


class PayrollEntry(models.Model):
    """Monthly payroll calculation per employee — frozen at period close."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payroll_entries')
    compliance_period = models.ForeignKey(
        CompliancePeriod, on_delete=models.CASCADE, related_name='payroll_entries',
    )
    gross_salary = models.DecimalField(max_digits=10, decimal_places=2)
    regular_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    overtime_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    overtime_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_gross = models.DecimalField(max_digits=10, decimal_places=2)
    paye_amount = models.DecimalField(max_digits=10, decimal_places=2)
    allowances = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    other_deductions = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    uif_employee = models.DecimalField(max_digits=8, decimal_places=2)
    uif_employer = models.DecimalField(max_digits=8, decimal_places=2)
    sdl_employer = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    net_pay = models.DecimalField(max_digits=10, decimal_places=2)
    is_frozen = models.BooleanField(default=False)
    paid_on = models.DateField(null=True, blank=True)
    payslip_emailed = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    calculated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payroll_entries'
        unique_together = ['employee', 'compliance_period']
        ordering = ['-compliance_period__period_start', 'employee__last_name']

    @property
    def employer_cost(self):
        """What this employee really costs the business this month."""
        return (self.total_gross or 0) + (self.uif_employer or 0) + (self.sdl_employer or 0)


# ============================================================================
# OPERATIONAL PLAYBOOK — TASK BOARD
# ============================================================================

class TaskFrequency(models.TextChoices):
    DAILY_MORNING = 'daily_morning', _('Daily — Morning Routine')
    DAILY_EVENING = 'daily_evening', _('Daily — Evening Routine')
    WEEKLY = 'weekly', _('Weekly')
    MONTHLY = 'monthly', _('Monthly')


class TaskTemplate(models.Model):
    """Role-based task definitions for the Operational Playbook dashboard."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(
        max_length=20,
        choices=UserRoleChoices.choices,
        db_index=True,
    )
    frequency = models.CharField(max_length=20, choices=TaskFrequency.choices)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    link_url = models.CharField(max_length=300, blank=True)
    is_blocking = models.BooleanField(
        default=False,
        help_text='If True, user cannot proceed past this task (e.g. shift open float).',
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'task_templates'
        ordering = ['frequency', 'sort_order']

    def __str__(self):
        return f"[{self.role}] {self.title}"


class TaskCompletion(models.Model):
    """Immutable audit log of task completions — one entry per user per task per day."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_template = models.ForeignKey(
        TaskTemplate, on_delete=models.CASCADE, related_name='completions',
    )
    completed_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='task_completions',
    )
    date_ref = models.DateField(db_index=True)  # The date this completion applies to
    completed_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = 'task_completions'
        unique_together = ['task_template', 'completed_by', 'date_ref']
        ordering = ['-completed_at']


# ============================================================================
# WEBSITE CONTENT MANAGEMENT
# ============================================================================

class ServiceCategory(models.TextChoices):
    IT_SUPPORT = 'it_support', _('IT Support')
    NETWORKING = 'networking', _('Networking')
    CCTV = 'cctv', _('CCTV & Security')
    SOFTWARE = 'software', _('Software')
    HARDWARE = 'hardware', _('Hardware')
    CLOUD = 'cloud', _('Cloud Services')
    OTHER = 'other', _('Other')


class ServicePrice(models.Model):
    """Publicly visible service offering — price editable from HQ Website module."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=30, choices=ServiceCategory.choices, default='it_support')
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=60, default='per visit', help_text='e.g. per device, per month, per hour')
    price_prefix = models.CharField(max_length=20, blank=True, help_text='e.g. "From" — shown before the price on the website')
    group = models.CharField(
        max_length=20, blank=True, db_index=True,
        help_text='Pricing card on the website this item appears in.',
        choices=[('hardware', 'Hardware & Support'), ('software', 'Software Products'),
                 ('pos', 'Point of Sale'), ('combo', 'Combos & Value Packages')],
    )
    is_featured = models.BooleanField(default=False, help_text='Show on website hero/pricing section')
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'service_prices'
        ordering = ['display_order', 'name']

    def __str__(self):
        return f"{self.name} — R{self.price}/{self.unit}"


class WebsiteSection(models.TextChoices):
    HERO = 'hero', _('Hero Banner')
    ABOUT = 'about', _('About Us')
    SERVICES = 'services', _('Services Section')
    PROCESS = 'process', _('How It Works')
    CTA = 'cta', _('Call To Action')
    CONTACT = 'contact', _('Contact Info')
    FOOTER = 'footer', _('Footer')


class WebsiteContent(models.Model):
    """Key-value store for editable website text/content blocks."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section = models.CharField(max_length=30, choices=WebsiteSection.choices)
    key = models.CharField(max_length=80, unique=True)
    label = models.CharField(max_length=120, help_text='Human-readable label shown in HQ editor')
    value = models.TextField()
    updated_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='website_edits',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'website_content'
        ordering = ['section', 'key']

    def __str__(self):
        return f"{self.section}::{self.key}"


# ============================================================================
# PAYMENTS
# ============================================================================

class PaymentStatus(models.TextChoices):
    PENDING = 'pending', _('Pending')
    COMPLETE = 'complete', _('Complete')
    FAILED = 'failed', _('Failed')
    CANCELLED = 'cancelled', _('Cancelled')


class Payment(models.Model):
    """Tracks every PayFast payment attempt tied to an invoice or a website order."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Our reference sent to PayFast as m_payment_id
    reference = models.CharField(max_length=60, unique=True, db_index=True)
    # PayFast's own transaction ID returned in ITN
    pf_payment_id = models.CharField(max_length=60, blank=True)
    # Optional link to an invoice
    invoice = models.ForeignKey(
        Invoice, null=True, blank=True, on_delete=models.SET_NULL, related_name='payments',
    )
    # Optional link to authenticated user
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='payments',
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    item_name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default='pending')
    # Payer details (populated from form or user profile)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    email_address = models.EmailField(blank=True)
    # Website-initiated payments carry the chosen service
    service_type = models.CharField(max_length=120, blank=True)
    # Raw ITN payload stored for audit trail
    raw_itn = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments'
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment {self.reference} — R{self.amount} [{self.status}]"


# ============================================================================
# REVENUE INTELLIGENCE — WiFi Subscribers, SLA Contracts, Allocation Settings
# ============================================================================

class SubscriberStatusChoices(models.TextChoices):
    ACTIVE = 'active', _('Active')
    SUSPENDED = 'suspended', _('Suspended')
    CANCELLED = 'cancelled', _('Cancelled')


class WifiSubscriber(models.Model):
    """
    Recurring WiFi/internet client managed via Axxess wholesale ISP.
    Each subscriber generates an auto-invoice on the 1st of every month.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    axxess_id = models.CharField(max_length=150, blank=True, help_text='Axxess device/SIM identifier')
    client_name = models.CharField(max_length=255, db_index=True)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    # Optional link to a portal Company — null for direct-pay clients
    company = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='wifi_subscriptions',
    )
    retail_price = models.DecimalField(max_digits=10, decimal_places=2, help_text='What you charge the client')
    wholesale_cost = models.DecimalField(max_digits=10, decimal_places=2, help_text='Axxess cost — editable anytime')
    billing_day = models.IntegerField(default=1, help_text='Day of month invoice is generated (default: 1st)')
    status = models.CharField(max_length=20, choices=SubscriberStatusChoices.choices, default='active', db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wifi_subscribers'
        ordering = ['client_name']

    def __str__(self):
        return f"{self.client_name} (R{self.retail_price}/month)"

    @property
    def gross_margin(self):
        return float(self.retail_price) - float(self.wholesale_cost)

    @property
    def is_loss_making(self):
        return self.wholesale_cost >= self.retail_price


class SLAContract(models.Model):
    """
    Recurring SLA retainer contract — generates a monthly invoice like WiFi.
    Call-outs above the retainer are raised as separate 'callout' invoices.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_name = models.CharField(max_length=255, db_index=True)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    company = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='sla_contracts',
    )
    monthly_retainer = models.DecimalField(max_digits=10, decimal_places=2)
    contract_description = models.TextField(blank=True, help_text='What the SLA covers')
    contract_start = models.DateField()
    contract_end = models.DateField(null=True, blank=True)
    billing_day = models.IntegerField(default=1)
    status = models.CharField(max_length=20, choices=SubscriberStatusChoices.choices, default='active', db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sla_contracts'
        ordering = ['client_name']

    def __str__(self):
        return f"{self.client_name} SLA — R{self.monthly_retainer}/month"


class ServiceTypeChoices(models.TextChoices):
    WIFI = 'wifi', _('WiFi / Internet')
    EMAIL = 'email', _('Email hosting')
    HOSTING = 'hosting', _('Website hosting')
    SLA = 'sla', _('SLA retainer')
    OTHER = 'other', _('Other service')


class BillingMode(models.TextChoices):
    HEAD_OFFICE = 'head_office', _('Billed to head office')
    SELF = 'self', _('Branch pays its own invoice')


class ClientSite(models.Model):
    """A branch of a client company (the Company is the head office)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='sites')
    name = models.CharField(max_length=200, help_text='e.g. "Jozini Branch"')
    address = models.TextField(blank=True)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    billing_mode = models.CharField(
        max_length=12, choices=BillingMode.choices, default=BillingMode.HEAD_OFFICE,
        help_text='Head office: this branch\'s services appear on the head office invoice. '
                  'Branch pays: it gets its own invoice.',
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'client_sites'
        ordering = ['company__name', 'name']
        unique_together = [('company', 'name')]

    def __str__(self):
        return f"{self.company.name} — {self.name}"


class Subscription(models.Model):
    """
    One recurring monthly service for a client (and optionally a branch):
    WiFi, email, website hosting, an SLA retainer, anything else. The monthly billing run
    combines everything due for the same paying client into ONE invoice with a line per service.

    WiFi subscribers and SLA contracts are mirrored into this table automatically
    (see legacy_wifi / legacy_sla) so they are billed together with everything else.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT, related_name='subscriptions')
    # For direct-pay clients that are not registered companies (no branches possible)
    client_name = models.CharField(max_length=255, blank=True, db_index=True)
    contact_email = models.EmailField(blank=True)
    site = models.ForeignKey(ClientSite, null=True, blank=True, on_delete=models.PROTECT, related_name='subscriptions')
    service_type = models.CharField(max_length=20, choices=ServiceTypeChoices.choices, default='wifi', db_index=True)
    description = models.CharField(max_length=255, blank=True, help_text='Shown on the invoice, e.g. "20Mbps fibre" or "domain + 5 mailboxes"')
    quantity = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, help_text='What the client pays per unit per month')
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text='What it costs you per unit per month')
    billing_day = models.PositiveSmallIntegerField(default=1, help_text='Invoice is due on this day of the month')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=SubscriberStatusChoices.choices, default='active', db_index=True)
    axxess_id = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    legacy_wifi = models.OneToOneField(WifiSubscriber, null=True, blank=True, on_delete=models.CASCADE, related_name='subscription')
    legacy_sla = models.OneToOneField(SLAContract, null=True, blank=True, on_delete=models.CASCADE, related_name='subscription')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subscriptions'
        ordering = ['company__name', 'client_name', 'site__name', 'service_type']

    def __str__(self):
        return f"{self.client_label} — {self.get_service_type_display()} R{self.monthly_total}"

    @property
    def client_label(self):
        return self.company.name if self.company_id else (self.client_name or '—')

    @property
    def monthly_total(self):
        return (self.quantity or 0) * (self.unit_price or 0)

    @property
    def monthly_cost(self):
        return (self.quantity or 0) * (self.unit_cost or 0)

    @property
    def is_managed_by_legacy(self):
        return bool(self.legacy_wifi_id or self.legacy_sla_id)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.site_id and self.site.company_id != self.company_id:
            raise ValidationError('The branch must belong to the same client company.')
        if not self.company_id and not self.client_name:
            raise ValidationError('Choose a client company or type a client name.')


class RevenueAllocation(models.Model):
    """
    Profit allocation percentages — mirrors the Setup tab of the Excel ledger.
    Singleton: only one record used (id=1). Editable from HQ Revenue Intelligence page.
    """
    reinvestment_pct = models.DecimalField(max_digits=5, decimal_places=4, default=0.15, help_text='e.g. 0.15 = 15%')
    opex_pct = models.DecimalField(max_digits=5, decimal_places=4, default=0.15, help_text='e.g. 0.15 = 15%')
    owner_pct = models.DecimalField(max_digits=5, decimal_places=4, default=0.70, help_text='e.g. 0.70 = 70%')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'revenue_allocation'

    def __str__(self):
        return f"Allocation: {float(self.reinvestment_pct)*100:.0f}% / {float(self.opex_pct)*100:.0f}% / {float(self.owner_pct)*100:.0f}%"


class CompanySettings(models.Model):
    """
    Singleton (id=1). Holds Rehumile's own contact & banking details.
    Edited from HQ Settings; rendered dynamically on invoices, website, and client portal.
    """
    # Contact
    company_name = models.CharField(max_length=200, default='Rehumile TMW')
    phone = models.CharField(max_length=50, default='')
    email = models.EmailField(default='')
    address = models.TextField(blank=True, default='')
    website = models.URLField(blank=True, default='')
    vat_number = models.CharField(max_length=50, blank=True, default='')

    # Banking
    account_name = models.CharField(max_length=100, default='')
    bank_name = models.CharField(max_length=100, default='')
    account_number = models.CharField(max_length=50, default='')
    branch_code = models.CharField(max_length=20, default='')
    swift_code = models.CharField(max_length=20, blank=True, default='')

    # Invoice defaults
    vat_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0.00)
    payment_terms = models.TextField(
        default='Payment is due as per terms. Please use the invoice number as reference. '
                'Late payments may attract interest as per our standard terms.'
    )

    payroll_sdl_enabled = models.BooleanField(
        default=False,
        help_text='Charge the 1% Skills Development Levy on payroll. Employers with an annual payroll under R500,000 are exempt.',
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'company_settings'

    def __str__(self):
        return f'Company Settings ({self.company_name})'

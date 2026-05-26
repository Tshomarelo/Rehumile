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
        return f"INV-{self.invoice_number} ({self.company.name})"


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

# Django Database Implementation Guide

## Overview
This document describes the comprehensive Django database schema for the Rehumile Portal IMS system. The database supports multi-tenant architecture with dual dashboards:
- **Client Dashboard**: Company-specific ticket management
- **HQ Dashboard**: System-wide administration

## Architecture Principles

### 1. Multi-Tenancy
- Every company has isolated data (company_id foreign key)
- HQ admins have access to all companies (company_id = NULL)
- Row-level security enforced in views/serializers
- Queries automatically filtered by user's company

### 2. User Role-Based Access
```
ADMIN (HQ)    → All system access
AGENT         → Company incidents only
FINANCE       → Billing management
CLIENT        → Own company only
VIEWER        → Read-only analytics
```

### 3. Data Isolation Pattern
```python
# Example queryset filtering
def get_incidents(user):
    if user.is_hq_admin():
        return Incident.objects.all()
    else:
        return Incident.objects.filter(company=user.company)
```

## Database Models

### Core Authentication Models

#### **Company**
Represents client organizations in the system.

**Key Fields:**
- `id` (UUID): Primary key
- `name` (String): Company name (unique)
- `slug` (String): URL-friendly identifier
- `sla_type` (Choice): Bronze/Silver/Gold
- `status` (Choice): Active/Inactive/Suspended
- `contact_person`, `contact_email`, `contact_phone`: Contact info
- `billing_*`: Complete billing address

**Relationships:**
- Has many `users` (1:N)
- Has many `incidents` (1:N)
- Has many `invoices` (1:N)
- Has one `billing_info` (1:1)

**Indexes:**
- `status, created_at`
- `sla_type`

---

#### **User (extends AbstractUser)**
Custom user model with role-based access control.

**Key Fields:**
- `id` (UUID): Primary key
- `email` (String): Unique email
- `role` (Choice): Admin/Agent/Finance/Client/Viewer
- `company` (FK): Company association (null for HQ Admin)
- `status` (Choice): Active/Inactive/Suspended
- `custom_permissions` (JSON): Granular permission flags

**Helper Methods:**
```python
user.is_hq_admin()      # Check if HQ admin
user.is_agent()         # Check if support agent
user.is_finance()       # Check if finance user
user.is_client()        # Check if client user
```

**Indexes:**
- `email` (unique)
- `role, company`
- `status`

---

#### **UserProfile**
Extended user information (OneToOne with User).

**Key Fields:**
- `phone_number`: Contact number
- `job_title`, `department`: Professional info
- `email_notifications`: Alert preferences
- `is_available`: Agent availability status
- `expertise_areas` (JSON): Agent specialties
- `max_assignments`: Max concurrent tickets

---

### Incident Management Models

#### **SLAConfig**
Configuration for SLA tiers (Bronze/Silver/Gold).

**Key Fields:**
- `sla_type` (Choice): Unique SLA level
- `response_time_hours` (Integer): Hours to respond
- `resolution_time_hours` (Integer): Hours to resolve
- `available_24_7` (Boolean): Always on or business hours
- `business_hours_start`, `business_hours_end` (Time)

**Sample Data:**
```
Bronze:   4h response, 24h resolution, Business hours
Silver:   2h response, 12h resolution, 24/7
Gold:     1h response, 4h resolution, 24/7
```

---

#### **Incident**
Core ticket/issue model.

**Key Fields:**
- `id` (UUID): Primary key
- `ticket_id` (String): Unique ticket number (e.g., IMS-001)
- `title`, `description`: Issue details
- `category`: Hardware/Software/Network/Database/Security/Other
- `company` (FK): Multi-tenant scope
- `submitted_by`, `assigned_to`: User references
- `status`: Open/In Progress/Resolved/Closed
- `priority`: Low/Medium/High/Critical
- `response_deadline`, `resolution_deadline`: SLA timestamps
- `is_sla_breached`: Breach indicator
- `hours_worked`, `billable_amount`: Billing info
- `resolution_notes`: Final notes

**Methods:**
```python
incident.calculate_sla_deadlines()  # Set deadlines based on SLA
incident.check_sla_breach()         # Check and update breach status
```

**Indexes:**
- `company, status`
- `company, priority`
- `is_sla_breached, resolution_deadline`
- `assigned_to, status`

---

#### **IncidentComment**
Discussion thread on incidents.

**Key Fields:**
- `incident` (FK): Parent incident
- `author` (FK): Comment author
- `comment_text`: Comment content
- `is_internal`: Internal-only flag
- `is_edited`: Edit tracking

**Logic:**
- Internal comments visible to HQ/Agents only
- Client-visible comments shown in client dashboard
- Thread ordering: earliest first

---

#### **IncidentAttachment**
File uploads for incidents.

**Key Fields:**
- `incident` (FK): Parent incident
- `file_name`, `file_path`: File reference
- `file_size`, `file_type`: File metadata
- `uploaded_by` (FK): Uploader user

**Notes:**
- `file_path` can be S3 URL, local path, etc.
- Deleted incidents cascade delete attachments

---

#### **IncidentTimeline**
Activity audit trail for incidents.

**Key Fields:**
- `incident` (FK): Parent incident
- `action_type`: Created/Status Changed/Assigned/etc.
- `description`: Human-readable action
- `old_value`, `new_value` (JSON): Change details
- `performed_by` (FK): Who made the change

**Action Types:**
- `created`: Incident created
- `status_changed`: Status updated
- `priority_changed`: Priority changed
- `assigned`: First assignment
- `reassigned`: Reassignment
- `commented`: Comment added
- `attachment_added`: File uploaded
- `escalated`: Escalated to higher level
- `sla_breached`: SLA breach detected

---

#### **SLABreach**
Separate model tracking SLA breaches for analytics.

**Key Fields:**
- `incident` (FK): Affected incident
- `company` (FK): Company context
- `breach_type`: Response/Resolution
- `breached_at`, `resolved_at`: Timestamps
- `time_over`: Minutes past deadline

**Purpose:**
- Easy querying for SLA reports
- Historical breach tracking
- Company SLA compliance metrics

---

### Billing Models

#### **Invoice**
Billing document for companies.

**Key Fields:**
- `invoice_number` (String): Unique invoice ID
- `company` (FK): Company billed
- `billing_period_start`, `billing_period_end`: Billing dates
- `subtotal`, `tax_amount`, `total_amount`: Financial amounts
- `ticket_count`, `hours_worked`: Usage summary
- `status`: Draft/Sent/Paid/Overdue/Cancelled
- `due_date`, `payment_date`: Payment dates
- `notes`: Invoice notes

**Status Flow:**
```
Draft → Sent → Paid
              ↓
           Overdue (if past due_date)
```

**Indexes:**
- `company, status`
- `billing_period_start, billing_period_end`

---

#### **InvoiceItem**
Line items in invoices.

**Key Fields:**
- `invoice` (FK): Parent invoice
- `incident` (FK): Related incident (if any)
- `description`: Item description
- `quantity`, `unit_price`: Quantity and rate
- `amount`: Total (quantity × price)
- `item_type`: Incident/Service/Support Hours/Other

**Purpose:**
- Detailed invoice breakdown
- Shows what client is charged for
- Links incidents to invoice lines

---

#### **CompanyBillingInfo**
Extended billing configuration (OneToOne with Company).

**Key Fields:**
- `company` (FK): Company reference
- `billing_frequency`: Monthly/Quarterly/Annual
- `hourly_rate`, `incident_fee`: Pricing
- `tax_id`, `tax_rate`: Tax info
- `payment_terms_days`: Net 30/60/etc.
- `credit_limit`, `current_balance`: Credit tracking

---

### Notification Models

#### **Notification**
System alerts for users.

**Key Fields:**
- `user` (FK): Recipient
- `notification_type`: SLA Warning/Breach/New Incident/Assignment/Invoice/General
- `title`, `message`: Alert content
- `incident`, `invoice` (FK): Related objects
- `is_read`: Read status
- `metadata` (JSON): Additional data

**Use Cases:**
- SLA approaching deadline → Notification to HQ
- Incident assigned → Notification to Agent
- Invoice created → Notification to Finance
- New ticket → Notification to HQ

---

### Audit & Analytics Models

#### **AuditLog**
Complete audit trail of all changes.

**Key Fields:**
- `user` (FK): Who made the change
- `action`: Create/Update/Delete
- `model_name`: Model changed
- `object_id`: Object ID
- `old_values`, `new_values` (JSON): Before/after
- `ip_address`, `user_agent`: Request context
- `created_at`: When changed

**Compliance:**
- Records all modifications for audit
- Helps troubleshoot issues
- Tracks user actions

---

#### **DashboardMetric**
Pre-calculated metrics for performance.

**Key Fields:**
- `metric_name`: Dashboard metric name
- `metric_value` (JSON): Calculated value
- `company` (FK): Scoped company (null for system)
- `metric_date`: Calculation date

**Metrics:**
- Total incidents
- Open/Resolved/Closed counts
- SLA compliance rate
- Revenue by company
- Agent performance stats

**Note:** Updated daily via management command for performance.

---

## Data Flow Examples

### 1. Client Creates Incident
```
POST /api/incidents
├─ Create Incident record (status=Open)
├─ Generate ticket_id (IMS-001)
├─ Calculate SLA deadlines via calculate_sla_deadlines()
├─ Create IncidentTimeline (action=created)
├─ Send Notification to HQ admin
└─ Return incident to client
```

### 2. HQ Assigns Incident
```
PATCH /api/incidents/{id}/assign
├─ Update incident.assigned_to
├─ Create IncidentTimeline (action=assigned)
├─ Send Notification to agent
├─ Update AuditLog
└─ Return updated incident
```

### 3. Agent Adds Comment
```
POST /api/incidents/{id}/comments
├─ Create IncidentComment
├─ Update incident.updated_at
├─ Create IncidentTimeline (action=commented)
├─ Send Notification to client (if external)
└─ Return comment
```

### 4. SLA Breach Detection (Scheduled Task)
```
Every 5 minutes:
├─ Query: incidents where status != closed AND resolution_deadline < now
├─ For each breached incident:
│  ├─ Set is_sla_breached = True
│  ├─ Create SLABreach record
│  ├─ Create Notification to HQ
│  └─ Create IncidentTimeline
└─ Update DashboardMetric
```

### 5. Monthly Invoice Generation
```
POST /api/invoices
├─ Query incidents for company in period
├─ Calculate total hours_worked
├─ Look up hourly_rate from CompanyBillingInfo
├─ Create Invoice (status=Draft)
├─ Create InvoiceItem for each incident
├─ Calculate total_amount with tax
├─ Send Notification to Finance
└─ Return invoice for review
```

## Database Indexes

### Performance-Critical Indexes
```
incidents (company_id, status)          -- List open incidents
incidents (company_id, priority)        -- High-priority filter
incidents (is_sla_breached, resolution_deadline)  -- SLA monitoring
incidents (assigned_to, status)         -- Agent workload
invoices (company_id, status)           -- Invoice search
users (role, company_id)                -- User filtering
notifications (user_id, is_read)        -- Notification list
```

## Query Patterns

### Common Queries

```python
# Get open incidents for a company
incidents = Incident.objects.filter(
    company=company,
    status=StatusChoices.OPEN
).order_by('-priority', 'response_deadline')

# Get SLA breached incidents
breached = Incident.objects.filter(
    is_sla_breached=True,
    status__in=['open', 'in_progress']
).select_related('company', 'assigned_to')

# Get invoices for a period
invoices = Invoice.objects.filter(
    company=company,
    billing_period_start__gte=start_date,
    billing_period_end__lte=end_date
).prefetch_related('items')

# Get user's unread notifications
notifications = Notification.objects.filter(
    user=user,
    is_read=False
).order_by('-created_at')[:20]

# Get agent performance
agent_stats = Incident.objects.filter(
    assigned_to=agent,
    status__in=['resolved', 'closed']
).aggregate(
    total=Count('id'),
    avg_hours=Avg('hours_worked'),
    avg_resolution_hours=Avg(
        ExpressionWrapper(
            F('resolved_at') - F('created_at'),
            output_field=DurationField()
        ) / 3600  # Convert to hours
    )
)
```

## Setup Instructions

### 1. Create Django App
```bash
python manage.py startapp ims
```

### 2. Add to settings.py
```python
INSTALLED_APPS = [
    ...
    'ims',
    'rest_framework',
]

# Custom User Model
AUTH_USER_MODEL = 'ims.User'
```

### 3. Make Migrations
```bash
python manage.py makemigrations ims
python manage.py migrate ims
```

### 4. Create Superuser
```bash
python manage.py createsuperuser
```

### 5. Load SLA Configurations
```python
from ims.models import SLAConfig

SLAConfig.objects.create(
    sla_type='bronze',
    response_time_hours=24,
    resolution_time_hours=72,
    available_24_7=False
)
# ... repeat for silver and gold
```

### 6. Create Initial Admin
```python
from ims.models import User

User.objects.create_superuser(
    email='admin@rehumile.com',
    password='secure_password',
    first_name='Admin',
    last_name='User',
    role='admin'
)
```

## Signals & Automation

### Important Signals to Implement

```python
# Auto-calculate SLA on incident creation
@receiver(post_save, sender=Incident)
def calculate_sla(sender, instance, created, **kwargs):
    if created:
        instance.calculate_sla_deadlines()
        instance.save()

# Track changes in AuditLog
@receiver(post_save, sender=Incident)
def log_incident_change(sender, instance, created, **kwargs):
    if not created:
        AuditLog.objects.create(
            action='update',
            model_name='Incident',
            object_id=str(instance.id),
            new_values={...}
        )

# Generate InvoiceItems from incidents
@receiver(post_save, sender=Invoice)
def generate_invoice_items(sender, instance, created, **kwargs):
    if created:
        incidents = Incident.objects.filter(
            company=instance.company,
            created_at__range=[
                instance.billing_period_start,
                instance.billing_period_end
            ]
        )
        for incident in incidents:
            InvoiceItem.objects.create(
                invoice=instance,
                incident=incident,
                description=f"{incident.ticket_id}: {incident.title}",
                ...
            )
```

## Validation Rules

### Incident Validation
- `title` cannot be empty
- `priority` must be valid choice
- `company` must exist
- `resolution_deadline` > `response_deadline`
- Only CLOSED/RESOLVED incidents can have `hours_worked` > 0

### Invoice Validation
- `billing_period_start` < `billing_period_end`
- `total_amount` = `subtotal` + `tax_amount`
- Status transitions: Draft → Sent → Paid (or Overdue)
- Cannot delete sent/paid invoices

### User Validation
- Email must be unique
- Password must meet strength requirements
- Client users must have a company assigned
- Admin users must have company_id = NULL

## Performance Optimization Tips

### 1. Use Select_Related for Foreign Keys
```python
incidents = Incident.objects.select_related(
    'company', 'assigned_to', 'submitted_by'
)
```

### 2. Use Prefetch_Related for Reverse Relations
```python
companies = Company.objects.prefetch_related(
    'incidents',
    'users',
    'invoices'
)
```

### 3. Use Only() for Specific Fields
```python
users = User.objects.only('id', 'email', 'role')
```

### 4. Pagination
```python
from rest_framework.pagination import PageNumberPagination

paginator = PageNumberPagination()
paginator.page_size = 20
results = paginator.paginate_queryset(queryset, request)
```

## Backup & Disaster Recovery

### Database Backup
```bash
# PostgreSQL
pg_dump -U user -d ims_db > backup.sql

# Restore
psql -U user -d ims_db < backup.sql
```

### Django Fixtures
```bash
# Export data
python manage.py dumpdata > data.json

# Import data
python manage.py loaddata data.json
```

## Monitoring & Maintenance

### Check Database Health
```bash
python manage.py dbshell
SELECT COUNT(*) FROM incidents;
SELECT COUNT(*) FROM invoices WHERE status='draft';
```

### Rebuild Indexes
```sql
REINDEX DATABASE ims_db;
```

### Analyze Query Performance
```python
from django.db import connection
from django.test.utils import CaptureQueriesContext

with CaptureQueriesContext(connection) as ctx:
    incidents = Incident.objects.filter(company=company)
    print(f"Executed {len(ctx)} queries")
```

## Summary

This Django database provides:
- ✅ Multi-tenant architecture
- ✅ Comprehensive incident tracking
- ✅ Full billing & invoicing system
- ✅ SLA management & monitoring
- ✅ Audit trails & compliance
- ✅ Notification system
- ✅ Role-based access control
- ✅ Analytics & reporting foundation

The models are production-ready and support all requirements for both Client and HQ dashboards.

# Rehumile Portal IMS - Entity Relationship Diagram (ERD)

## Visual Database Structure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       REHUMILE PORTAL IMS DATABASE                          │
└─────────────────────────────────────────────────────────────────────────────┘

                              ┌──────────────┐
                              │   COMPANY    │
                              ├──────────────┤
                              │ id (UUID)    │
                              │ name         │
                              │ sla_type     │◄─────┐
                              │ status       │      │
                              │ contact_*    │      │
                              │ billing_*    │      │
                              └──────────────┘      │
                                    │               │
                    ┌───────────────┼───────────────┤
                    │               │               │
                    ▼               ▼               ▼
            ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
            │    USER      │  │  INCIDENT    │  │  COMPANY BILLING │
            ├──────────────┤  ├──────────────┤  ├──────────────────┤
            │ id (UUID)    │  │ id (UUID)    │  │ id (UUID)        │
            │ email        │  │ ticket_id    │  │ hourly_rate      │
            │ role         │  │ title        │  │ tax_rate         │
            │ company_id   │  │ status       │  │ payment_terms    │
            │ status       │  │ priority     │  │ credit_limit     │
            │ permissions  │  │ category     │  └──────────────────┘
            └──────────────┘  │ company_id   │
                    │         │ submitted_by │
                    │         │ assigned_to  │
                    │         │ response_*   │
                    │         │ resolution_* │
                    ▼         │ sla_breached │
            ┌──────────────┐  │ hours_worked │
            │ USER PROFILE │  │ billable_amt │
            ├──────────────┤  └──────────────┘
            │ id (UUID)    │         │
            │ phone        │    ┌────┼────┬─────────────┐
            │ job_title    │    │    │    │             │
            │ avatar_url   │    ▼    ▼    ▼             ▼
            │ expertise    │  ┌──────────┐  ┌────────────┐  ┌──────────────┐
            │ email_notif  │  │ INCIDENT │  │ INCIDENT   │  │    SLA       │
            └──────────────┘  │ COMMENT  │  │ ATTACHMENT │  │   CONFIG     │
                              ├──────────┤  ├────────────┤  ├──────────────┤
                              │ id       │  │ id         │  │ id           │
                              │ incident │  │ incident   │  │ sla_type     │
                              │ author   │  │ file_name  │  │ response_hrs │
                              │ comment  │  │ file_path  │  │ resolution_* │
                              │ is_intl  │  │ file_size  │  │ available_24 │
                              └──────────┘  │ uploaded_by│  └──────────────┘
                                            └────────────┘
                              ┌──────────────┐
                              │   INCIDENT   │
                              │   TIMELINE   │
                              ├──────────────┤
                              │ id           │
                              │ incident     │
                              │ action_type  │
                              │ description  │
                              │ old_value    │
                              │ new_value    │
                              │ performed_by │
                              └──────────────┘

            ┌──────────────────────────────────────────────────────┐
            │                    INVOICING                          │
            └──────────────────────────────────────────────────────┘

            ┌──────────────┐         ┌──────────────┐
            │   INVOICE    │────────►│ INVOICE ITEM │
            ├──────────────┤         ├──────────────┤
            │ id (UUID)    │1    N   │ id (UUID)    │
            │ invoice_num  │         │ invoice_id   │
            │ company_id   │         │ incident_id  │
            │ period_start │         │ description  │
            │ period_end   │         │ quantity     │
            │ subtotal     │         │ unit_price   │
            │ tax_amount   │         │ amount       │
            │ total_amount │         └──────────────┘
            │ status       │
            │ due_date     │
            │ payment_date │
            └──────────────┘

            ┌──────────────────────────────────────────────────────┐
            │              NOTIFICATIONS & AUDIT                    │
            └──────────────────────────────────────────────────────┘

            ┌──────────────┐         ┌──────────────┐
            │ NOTIFICATION │         │  AUDIT LOG   │
            ├──────────────┤         ├──────────────┤
            │ id           │         │ id           │
            │ user_id      │         │ user_id      │
            │ type         │         │ action       │
            │ title        │         │ model_name   │
            │ message      │         │ object_id    │
            │ incident_id  │         │ old_values   │
            │ invoice_id   │         │ new_values   │
            │ is_read      │         │ ip_address   │
            │ read_at      │         │ user_agent   │
            └──────────────┘         └──────────────┘

            ┌──────────────┐
            │ SLA BREACH   │
            ├──────────────┤
            │ id           │
            │ incident_id  │
            │ company_id   │
            │ breach_type  │
            │ breached_at  │
            │ resolved_at  │
            │ time_over    │
            └──────────────┘

            ┌──────────────┐
            │ DASHBOARD    │
            │ METRIC       │
            ├──────────────┤
            │ id           │
            │ metric_name  │
            │ metric_value │
            │ company_id   │
            │ metric_date  │
            └──────────────┘
```

---

## Relationship Types

### One-to-One Relationships (1:1)
```
User         ◄─────────────► UserProfile
             (OneToOneField)

Company      ◄─────────────► CompanyBillingInfo
             (OneToOneField)
```

### One-to-Many Relationships (1:N)
```
Company      ◄─────────────► User
             (ForeignKey)
             (Multiple users per company)

Company      ◄─────────────► Incident
             (ForeignKey)
             (Multiple incidents per company)

Incident     ◄─────────────► IncidentComment
             (ForeignKey)
             (Multiple comments per incident)

Incident     ◄─────────────► IncidentAttachment
             (ForeignKey)
             (Multiple attachments per incident)

Incident     ◄─────────────► IncidentTimeline
             (ForeignKey)
             (Multiple timeline events per incident)

Incident     ◄─────────────► SLABreach
             (ForeignKey)
             (Multiple breaches per incident)

Invoice      ◄─────────────► InvoiceItem
             (ForeignKey)
             (Multiple items per invoice)

Company      ◄─────────────► Invoice
             (ForeignKey)
             (Multiple invoices per company)

User         ◄─────────────► Notification
             (ForeignKey)
             (Multiple notifications per user)

User         ◄─────────────► AuditLog
             (ForeignKey)
             (Multiple audit entries per user)

Company      ◄─────────────► SLABreach
             (ForeignKey)
             (Multiple breaches per company)

Company      ◄─────────────► DashboardMetric
             (ForeignKey)
             (Multiple metrics per company)
```

### Multiple Foreign Keys from Same Model
```
Incident
├─ submitted_by  ────► User (who created)
├─ assigned_to   ────► User (who is assigned)
└─ escalated_to  ────► User (who escalated to)

IncidentComment
├─ author        ────► User (who commented)

IncidentAttachment
├─ uploaded_by   ────► User (who uploaded)

IncidentTimeline
├─ performed_by  ────► User (who performed action)
```

---

## Data Flow Diagram

```
INCIDENT CREATION
─────────────────
Client Portal
    │
    ▼
POST /api/incidents
    │
    ├─► Create Incident (status=open)
    │
    ├─► Generate ticket_id
    │
    ├─► Calculate SLA deadlines
    │   - Get company.sla_type
    │   - Look up SLAConfig
    │   - Set response_deadline
    │   - Set resolution_deadline
    │
    ├─► Create IncidentTimeline (action=created)
    │
    ├─► Create Notification to HQ
    │
    └─► Return Incident to client


INCIDENT ASSIGNMENT
───────────────────
HQ Admin
    │
    ▼
PATCH /api/incidents/{id}/assign
    │
    ├─► Update assigned_to = Agent
    │
    ├─► Create IncidentTimeline (action=assigned)
    │
    ├─► Create Notification to Agent
    │
    ├─► Update AuditLog
    │
    └─► Return updated Incident


INCIDENT UPDATE
───────────────
Agent
    │
    ├─► Update status/priority
    │   │
    │   ├─► Create IncidentTimeline
    │   ├─► Create Notification
    │   └─► Update AuditLog
    │
    ├─► Add comment
    │   │
    │   ├─► Create IncidentComment
    │   ├─► Create IncidentTimeline (action=commented)
    │   ├─► Create Notification
    │   └─► Return comment
    │
    ├─► Upload attachment
    │   │
    │   ├─► Create IncidentAttachment
    │   ├─► Create IncidentTimeline (action=attachment_added)
    │   └─► Return attachment
    │
    └─► Update hours_worked
        │
        ├─► Update Incident.hours_worked
        ├─► Create IncidentTimeline
        └─► Update AuditLog


SLA MONITORING (Background Task)
────────────────────────────────
Every 5 minutes:
    │
    ├─► Query: Incidents where status != closed AND resolution_deadline < now
    │
    ├─► For each breached incident:
    │   ├─► Set is_sla_breached = True
    │   ├─► Set sla_breach_date = now
    │   ├─► Create SLABreach record
    │   ├─► Create IncidentTimeline (action=sla_breached)
    │   ├─► Create Notification to HQ (type=sla_breach)
    │   └─► Update AuditLog
    │
    └─► Update DashboardMetric


INVOICE GENERATION
──────────────────
Monthly (Scheduled):
    │
    ├─► Query: Incidents for company in billing period
    │
    ├─► Create Invoice (status=draft)
    │   │
    │   ├─ invoice_number (auto-generated)
    │   ├─ billing_period_start
    │   ├─ billing_period_end
    │   ├─ ticket_count
    │   ├─ hours_worked (sum)
    │   └─ total_amount = hours × rate + tax
    │
    ├─► For each billable incident:
    │   │
    │   └─► Create InvoiceItem
    │       ├─ incident_id
    │       ├─ description
    │       ├─ hours_worked (quantity)
    │       ├─ hourly_rate (unit_price)
    │       └─ amount
    │
    ├─► Create Notification to Finance (type=invoice)
    │
    └─► Ready for Finance review


INVOICE SENDING
───────────────
Finance Admin
    │
    ▼
Update Invoice status: Draft → Sent
    │
    ├─► sent_at = now
    │
    ├─► Create Notification to Client (type=invoice)
    │
    ├─► Create AuditLog
    │
    └─► Generate PDF (optional)


PAYMENT TRACKING
────────────────
Finance receives payment
    │
    ▼
Update Invoice status: Sent → Paid
    │
    ├─► payment_date = now
    │
    ├─► Create Notification to Company
    │
    └─► Create AuditLog
```

---

## Database Metrics & Stats

### Model Count
- **Total Models**: 17
- **Authentication**: 4
- **Incident Management**: 6
- **Billing**: 2
- **Notifications/Audit**: 3
- **Analytics**: 2 (SLABreach, DashboardMetric)

### Field Count
- **Total Fields**: 150+
- **Foreign Keys**: 30+
- **Choice Fields**: 15+
- **JSON Fields**: 5
- **Timestamp Fields**: 40+

### Index Count
- **Performance Indexes**: 8+
- **Unique Constraints**: 5

### Relationship Count
- **One-to-One**: 2
- **One-to-Many**: 15+
- **Multiple FKs from Same Model**: 5

---

## Access Control Matrix

```
┌─────────────┬────────┬──────┬────────────┬──────────┬────────┐
│ Resource    │ Admin  │Agent │ Finance    │ Client   │ Viewer │
├─────────────┼────────┼──────┼────────────┼──────────┼────────┤
│ Companies   │ CRUD   │ R    │ R          │ Self     │ R      │
│ Users       │ CRUD   │ R    │ R          │ Self     │ R      │
│ Incidents   │ CRUD   │ Own  │ R          │ Own      │ R      │
│ Invoices    │ R      │ -    │ CRUD       │ Own      │ R      │
│ Reports     │ R      │ Own  │ R          │ Own      │ R      │
│ Admin Panel │ Yes    │ No   │ Limited    │ No       │ No     │
└─────────────┴────────┴──────┴────────────┴──────────┴────────┘

Legend: CRUD (Create/Read/Update/Delete), R (Read-only), Own (Own data)
```

---

## Query Performance Guide

### Fast Queries (with indexes)
```sql
-- Get company incidents by status
SELECT * FROM incidents 
WHERE company_id = ? AND status = 'open'
ORDER BY priority DESC

-- Get unread notifications
SELECT * FROM notifications 
WHERE user_id = ? AND is_read = false
ORDER BY created_at DESC

-- Get breached incidents
SELECT * FROM incidents 
WHERE is_sla_breached = true AND status != 'closed'
```

### Queries to Optimize
```sql
-- Slow: No index on (company_id, role)
SELECT * FROM users WHERE company_id = ? AND role = 'agent'
✓ Fixed: Index on (company_id, role)

-- Slow: No index on created_at alone
SELECT * FROM incidents WHERE created_at > ? 
✓ Use: Partial index or include in compound index

-- Slow: Multiple JOINs without prefetch
SELECT incident, comments, attachments FROM incidents
✓ Use: select_related, prefetch_related
```

---

This ERD represents the complete data structure for the Rehumile Portal IMS system, accurately modeling all client and HQ dashboard requirements, forms, tables, and system workflows.

# IMS API Endpoints

## Authentication Endpoints

### POST /api/auth/login
Login user and return JWT token
**Request:** `{ email, password }`
**Response:** `{ token, user: { id, email, role, company_id } }`

### POST /api/auth/logout
Invalidate user session

### GET /api/auth/me
Get current authenticated user

### POST /api/auth/refresh-token
Refresh JWT token

---

## Company Management Endpoints

### GET /api/companies
List all companies (paginated)
**Query:** `?skip=0&limit=10&status=active`
**Response:** `{ data: [], total: int }`

### GET /api/companies/:id
Get company details including linked users

### POST /api/companies
Create new company (HQ Admin only)
**Request:** `{ name, contact_person, contact_email, sla_type, billing_email }`

### PUT /api/companies/:id
Update company details
**Request:** `{ name, contact_person, contact_email, sla_type, status }`

### PATCH /api/companies/:id/status
Change company active/inactive status

### GET /api/companies/:id/users
Get all users linked to company

---

## User Management Endpoints

### GET /api/users
List all users (paginated, HQ only)
**Query:** `?company_id=xxx&role=agent&skip=0&limit=10`

### GET /api/users/:id
Get user details

### POST /api/users
Create new user (HQ only)
**Request:** `{ email, first_name, last_name, role, company_id, password }`

### PUT /api/users/:id
Update user details
**Request:** `{ first_name, last_name, role, permissions }`

### POST /api/users/:id/reset-password
Send password reset link

### PATCH /api/users/:id/status
Activate/Deactivate user

### GET /api/users/:id/permissions
Get user permissions

### PUT /api/users/:id/permissions
Update user permissions

---

## Incident Management Endpoints

### GET /api/incidents
List all incidents (multi-tenant view)
**Query:** `?company_id=xxx&status=open&priority=high&skip=0&limit=20`
**Response:** `{ data: [], total: int, sla_breached_count: int }`

### GET /api/incidents/:id
Get incident details with comments and attachments

### GET /api/incidents/:id/timeline
Get incident activity timeline

### POST /api/incidents
Create new incident
**Request:** `{ title, description, category, priority, company_id }`

### PUT /api/incidents/:id
Update incident
**Request:** `{ title, description, status, priority, assigned_to }`

### PATCH /api/incidents/:id/assign
Assign/reassign incident to agent
**Request:** `{ assigned_to }`

### PATCH /api/incidents/:id/status
Update incident status
**Request:** `{ status }`

### PATCH /api/incidents/:id/priority
Update incident priority
**Request:** `{ priority }`

### POST /api/incidents/:id/comments
Add comment to incident
**Request:** `{ comment_text, is_internal }`

### GET /api/incidents/:id/comments
Get incident comments

### POST /api/incidents/:id/attachments
Upload file attachment

### GET /api/incidents/:id/attachments
Get incident attachments

### PATCH /api/incidents/:id/billable
Mark incident as billable/non-billable
**Request:** `{ is_billable, hours_worked }`

### POST /api/incidents/:id/escalate
Escalate incident to higher priority

---

## SLA Tracking Endpoints

### GET /api/sla/config
Get SLA configuration for all types

### GET /api/sla/breached
List incidents with SLA breaches
**Query:** `?company_id=xxx&days_breached=1`

### GET /api/sla/at-risk
List incidents at risk of SLA breach (within 2 hours)

### GET /api/incidents/:id/sla-status
Get SLA status for incident

---

## Billing & Invoicing Endpoints

### GET /api/invoices
List invoices (paginated)
**Query:** `?company_id=xxx&status=draft&skip=0&limit=10`

### GET /api/invoices/:id
Get invoice details

### POST /api/invoices
Create new invoice
**Request:** `{ company_id, billing_period_start, billing_period_end }`

### PUT /api/invoices/:id
Update invoice
**Request:** `{ status, total_amount }`

### PATCH /api/invoices/:id/status
Change invoice status (draft → sent → paid)
**Request:** `{ status }`

### GET /api/invoices/:id/pdf
Download invoice as PDF

### GET /api/invoices/:id/items
Get invoice line items

### POST /api/invoices/:id/items
Add line item to invoice
**Request:** `{ incident_id, description, quantity, unit_price }`

### GET /api/billing/company/:company_id/revenue
Get revenue for company in period
**Query:** `?start_date=2026-01-01&end_date=2026-12-31`

---

## Dashboard Analytics Endpoints

### GET /api/analytics/dashboard
Main dashboard KPIs
**Response:** `{ total_incidents, open_tickets, resolved_tickets, sla_compliance_rate, revenue }`

### GET /api/analytics/incidents-by-company
Incidents count per company

### GET /api/analytics/incidents-trend
Incidents over time (for chart)
**Query:** `?days=30`

### GET /api/analytics/sla-compliance
SLA compliance metrics per company

### GET /api/analytics/top-companies
Top companies by incident volume

### GET /api/analytics/agent-performance
Support agent performance metrics

---

## Notifications Endpoints

### GET /api/notifications
Get user's notifications (paginated)
**Query:** `?is_read=false&skip=0&limit=10`

### PATCH /api/notifications/:id/read
Mark notification as read

### POST /api/notifications/mark-all-read
Mark all notifications as read

### DELETE /api/notifications/:id
Delete notification

---

## Reports Endpoints

### GET /api/reports/incidents-by-status
Incident report by status

### GET /api/reports/incidents-by-priority
Incident report by priority

### GET /api/reports/company-summary
Company performance summary
**Query:** `?company_id=xxx&start_date=2026-01-01&end_date=2026-12-31`

### GET /api/reports/export
Export report as CSV/PDF
**Query:** `?type=incidents&format=pdf&date_from=2026-01-01&date_to=2026-12-31`

---

## General Response Format

### Success Response
```json
{
  "success": true,
  "data": {},
  "message": "Operation successful"
}
```

### Error Response
```json
{
  "success": false,
  "error": {
    "code": "INVALID_REQUEST",
    "message": "Human readable error message"
  }
}
```

---

## Client-Specific Endpoints

### GET /api/client/dashboard
Get client dashboard summary with company-specific data
**Response:** `{ total_tickets, open_tickets, resolved_tickets, recent_tickets, tickets_by_category, tickets_trend }`

### GET /api/client/tickets
List tickets for the logged-in user's company
**Query:** `?status=open&priority=high&skip=0&limit=20`
**Response:** `{ data: [], total: int }`

### POST /api/client/tickets
Create a new incident ticket
**Request:** `{ title, description, category, priority }`

### GET /api/client/tickets/:id
Get ticket details (client-visible comments only)

### POST /api/client/tickets/:id/comments
Add client comment to ticket
**Request:** `{ comment_text }`

### GET /api/client/notifications
Get notifications for the logged-in user
**Query:** `?is_read=false&skip=0&limit=10`

### GET /api/client/profile
Get the logged-in user's profile information

### PUT /api/client/profile
Update user profile
**Request:** `{ first_name, last_name }`

### PUT /api/client/password
Change user password
**Request:** `{ current_password, new_password }

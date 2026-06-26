"""
Rehumile Portal IMS - Incident Management System
Django application for multi-tenant incident management with dual dashboards.

This package contains:
- Complete database models for incident management
- User authentication and role-based access control
- Incident tracking and SLA monitoring
- Billing and invoicing system
- Notification system
- Admin interface

Models:
- Core: User, Company, UserProfile, CompanyBillingInfo
- Incidents: Incident, IncidentComment, IncidentAttachment, IncidentTimeline
- SLA: SLAConfig, SLABreach
- Billing: Invoice, InvoiceItem
- Notifications: Notification, AuditLog, DashboardMetric

Author: Development Team
Version: 1.0.0
"""

default_app_config = 'ims.apps.ImsConfig'

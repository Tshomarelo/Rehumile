from django.http import HttpResponse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / 'staticfiles'


def _serve(filename):
    html = (STATIC_DIR / filename).read_text(encoding='utf-8')
    return HttpResponse(html, content_type='text/html; charset=utf-8')


def website_home_view(request):
    return _serve('website-home.html')


def portal_login_view(request):
    return _serve('pages-sign-in.html')


def portal_forgot_password_view(request):
    return _serve('pages-forgot-password.html')


def portal_reset_confirm_view(request):
    return _serve('pages-reset-confirm.html')


def portal_index_view(request):
    return _serve('hq-dashboard.html')


def portal_incidents_view(request):
    return _serve('hq-incidents.html')


def portal_companies_view(request):
    return _serve('hq-companies.html')


def portal_users_view(request):
    return _serve('hq-users.html')


def portal_invoices_view(request):
    return _serve('hq-invoices.html')


def portal_reports_view(request):
    return _serve('hq-reports.html')


def portal_sla_monitor_view(request):
    return _serve('hq-sla-monitor.html')


def portal_hq_notifications_view(request):
    return _serve('hq-notifications.html')


def portal_audit_log_view(request):
    return _serve('hq-audit-log.html')


def portal_job_cards_view(request):
    return _serve('hq-job-cards.html')


def portal_inventory_view(request):
    return _serve('hq-inventory.html')


def portal_cash_management_view(request):
    return _serve('hq-cash-management.html')


def portal_financial_analytics_view(request):
    return _serve('hq-financial-analytics.html')


def portal_pos_view(request):
    return _serve('hq-pos.html')


def portal_vouchers_view(request):
    return _serve('hq-vouchers.html')


# ── Client portal pages ──────────────────────────────────────────────────────

def client_dashboard_view(request):
    return _serve('client-dashboard.html')


def client_tickets_view(request):
    return _serve('client-tickets.html')


def client_create_ticket_view(request):
    return _serve('client-create-ticket.html')


def client_ticket_detail_view(request):
    return _serve('client-ticket-detail.html')


def client_billing_view(request):
    return _serve('client-billing.html')


def client_profile_view(request):
    return _serve('client-profile.html')


def client_contact_view(request):
    return _serve('client-contact.html')


def client_notifications_view(request):
    return _serve('client-notifications.html')


# ── Compliance & HR pages ─────────────────────────────────────────────────────

def portal_compliance_view(request):
    return _serve('hq-compliance.html')


def portal_vat201_view(request):
    return _serve('hq-vat201.html')


def portal_emp201_view(request):
    return _serve('hq-emp201.html')


def portal_hr_view(request):
    return _serve('hq-hr.html')


def portal_playbook_view(request):
    return _serve('hq-playbook.html')


def portal_website_view(request):
    return _serve('hq-website.html')


def portal_wifi_sla_view(request):
    return _serve('hq-wifi-sla.html')


def portal_revenue_intelligence_view(request):
    return _serve('hq-revenue-intelligence.html')


def payment_success_view(request):
    return _serve('payment-success.html')


def payment_cancel_view(request):
    return _serve('payment-cancel.html')


def website_checkout_view(request):
    return _serve('website-checkout.html')


def portal_settings_view(request):
    return _serve('hq-settings.html')


def invoice_print_view(request, invoice_id):
    return _serve('invoice-print.html')

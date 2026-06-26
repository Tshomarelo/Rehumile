from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve as static_serve
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from ims.portal_views import (
    portal_login_view, portal_index_view,
    portal_incidents_view, portal_companies_view,
    portal_users_view, portal_invoices_view, portal_reports_view,
    portal_sla_monitor_view, portal_hq_notifications_view, portal_audit_log_view,
    portal_forgot_password_view, portal_reset_confirm_view,
    portal_job_cards_view, portal_inventory_view,
    portal_cash_management_view, portal_financial_analytics_view,
    portal_pos_view, portal_vouchers_view,
    portal_compliance_view, portal_vat201_view, portal_emp201_view,
    portal_hr_view, portal_playbook_view,
    client_dashboard_view, client_tickets_view, client_create_ticket_view,
    client_ticket_detail_view, client_billing_view, client_profile_view,
    client_contact_view, client_notifications_view,
    website_home_view,
)
from ims.views import ChangePasswordView, quote_request_view

_portal_patterns = [
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('api/', include('ims.urls')),
    path('login/', portal_login_view, name='portal-login'),
    path('password-reset/', portal_forgot_password_view, name='portal-forgot-password'),
    path('password-reset/confirm/', portal_reset_confirm_view, name='portal-reset-confirm'),
    path('dashboard/', portal_index_view, name='portal-dashboard'),
    path('incidents/', portal_incidents_view, name='portal-incidents'),
    path('companies/', portal_companies_view, name='portal-companies'),
    path('users/', portal_users_view, name='portal-users'),
    path('dashboard/job-cards/', portal_job_cards_view, name='portal-job-cards'),
    path('dashboard/inventory/', portal_inventory_view, name='portal-inventory'),
    path('invoices/', portal_invoices_view, name='portal-invoices'),
    path('reports/', portal_reports_view, name='portal-reports'),
    path('dashboard/pos/', portal_pos_view, name='portal-pos'),
    path('dashboard/vouchers/', portal_vouchers_view, name='portal-vouchers'),
    path('dashboard/cash-management/', portal_cash_management_view, name='portal-cash-management'),
    path('dashboard/financial-analytics/', portal_financial_analytics_view, name='portal-financial-analytics'),
    path('dashboard/sla-monitor/', portal_sla_monitor_view, name='portal-sla-monitor'),
    path('dashboard/notifications/', portal_hq_notifications_view, name='portal-hq-notifications'),
    path('dashboard/audit-log/', portal_audit_log_view, name='portal-audit-log'),
    path('client/', client_dashboard_view, name='client-dashboard'),
    path('client/tickets/', client_tickets_view, name='client-tickets'),
    path('client/tickets/create/', client_create_ticket_view, name='client-create-ticket'),
    path('client/tickets/detail/', client_ticket_detail_view, name='client-ticket-detail'),
    path('client/billing/', client_billing_view, name='client-billing'),
    path('client/profile/', client_profile_view, name='client-profile'),
    path('client/contact/', client_contact_view, name='client-contact'),
    path('client/notifications/', client_notifications_view, name='client-notifications'),
    path('api/quote/', quote_request_view, name='quote-request'),
    # Compliance & HR pages
    path('dashboard/compliance/', portal_compliance_view, name='portal-compliance'),
    path('dashboard/vat201/', portal_vat201_view, name='portal-vat201'),
    path('dashboard/emp201/', portal_emp201_view, name='portal-emp201'),
    path('dashboard/hr/', portal_hr_view, name='portal-hr'),
    path('dashboard/playbook/', portal_playbook_view, name='portal-playbook'),
]

urlpatterns = _portal_patterns + [
    path('portal/', include(_portal_patterns)),
    path('portal/static/<path:path>', static_serve, {'document_root': settings.STATIC_ROOT}),
    path('portal/media/<path:path>', static_serve, {'document_root': settings.MEDIA_ROOT}),
    path('', website_home_view, name='website-home'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

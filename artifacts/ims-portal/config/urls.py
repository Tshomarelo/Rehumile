from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from ims.portal_views import (
    portal_login_view, portal_index_view,
    portal_incidents_view, portal_companies_view,
    portal_users_view, portal_invoices_view, portal_reports_view,
    client_dashboard_view, client_tickets_view, client_create_ticket_view,
    client_ticket_detail_view, client_billing_view, client_profile_view,
    client_contact_view,
)
from ims.views import ChangePasswordView

urlpatterns = [
    # Django admin
    path('admin/', admin.site.urls),

    # API Schema & Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    # JWT Token endpoints
    path('api/auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/change-password/', ChangePasswordView.as_view(), name='change-password'),

    # IMS REST API
    path('api/', include('ims.urls')),

    # HQ portal frontend pages
    path('login/', portal_login_view, name='portal-login'),
    path('dashboard/', portal_index_view, name='portal-dashboard'),
    path('incidents/', portal_incidents_view, name='portal-incidents'),
    path('companies/', portal_companies_view, name='portal-companies'),
    path('users/', portal_users_view, name='portal-users'),
    path('invoices/', portal_invoices_view, name='portal-invoices'),
    path('reports/', portal_reports_view, name='portal-reports'),

    # Client portal pages
    path('client/', client_dashboard_view, name='client-dashboard'),
    path('client/tickets/', client_tickets_view, name='client-tickets'),
    path('client/tickets/create/', client_create_ticket_view, name='client-create-ticket'),
    path('client/tickets/detail/', client_ticket_detail_view, name='client-ticket-detail'),
    path('client/billing/', client_billing_view, name='client-billing'),
    path('client/profile/', client_profile_view, name='client-profile'),
    path('client/contact/', client_contact_view, name='client-contact'),

    # Root → login
    path('', RedirectView.as_view(url='/portal/login/', permanent=False), name='portal-root'),
]

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'companies', views.CompanyViewSet, basename='company')
router.register(r'users', views.UserViewSet, basename='user')
router.register(r'incidents', views.IncidentViewSet, basename='incident')
router.register(r'invoices', views.InvoiceViewSet, basename='invoice')

urlpatterns = [
    path('auth/login/', views.LoginView.as_view(), name='login'),
    path('auth/logout/', views.LogoutView.as_view(), name='logout'),
    path('auth/me/', views.MeView.as_view(), name='me'),
    path('auth/password-reset/', views.PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('auth/password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('dashboard/metrics/', views.DashboardMetricsView.as_view(), name='dashboard-metrics'),
    path('notifications/', views.NotificationsView.as_view(), name='notifications'),
    path('audit-log/', views.AuditLogView.as_view(), name='audit-log'),
    path('sla-breaches/', views.SLABreachListView.as_view(), name='sla-breaches'),
    path('incidents/<uuid:incident_id>/attachments/', views.IncidentAttachmentView.as_view(), name='incident-attachments'),
    # Workshop — Job Cards
    path('job-cards/', views.JobCardListView.as_view(), name='job-card-list'),
    path('job-cards/<uuid:pk>/', views.JobCardDetailView.as_view(), name='job-card-detail'),
    # Inventory
    path('inventory/', views.InventoryListView.as_view(), name='inventory-list'),
    path('inventory/transactions/', views.StockTransactionView.as_view(), name='stock-transaction'),
    # Cash Management
    path('shifts/', views.ShiftLogView.as_view(), name='shift-log'),
    path('cash-transactions/', views.CashTransactionListView.as_view(), name='cash-transaction-list'),
    # Vouchers
    path('vouchers/', views.VoucherView.as_view(), name='voucher'),
    # Financial Analytics
    path('financial-analytics/', views.FinancialAnalyticsView.as_view(), name='financial-analytics'),
    # SARS Compliance Staging Engine
    path('compliance/', views.CompliancePeriodListView.as_view(), name='compliance-period-list'),
    path('compliance/<uuid:pk>/', views.CompliancePeriodDetailView.as_view(), name='compliance-period-detail'),
    path('compliance/<uuid:pk>/vat201/', views.VAT201View.as_view(), name='vat201'),
    path('compliance/<uuid:pk>/emp201/', views.EMP201View.as_view(), name='emp201'),
    path('compliance/<uuid:pk>/emp201/csv/', views.EMP201View.as_view(), name='emp201-csv'),
    path('supplier-slips/', views.SupplierSlipOCRView.as_view(), name='supplier-slip-list'),
    path('supplier-slips/<uuid:pk>/', views.SupplierSlipOCRView.as_view(), name='supplier-slip-detail'),
    # HR & Payroll
    path('employees/', views.EmployeeListView.as_view(), name='employee-list'),
    path('employees/<uuid:pk>/', views.EmployeeDetailView.as_view(), name='employee-detail'),
    path('payroll/', views.PayrollView.as_view(), name='payroll'),
    path('payroll/<uuid:pk>/', views.PayrollView.as_view(), name='payroll-entry'),
    path('leave-requests/', views.LeaveRequestView.as_view(), name='leave-request-list'),
    path('leave-requests/<uuid:pk>/', views.LeaveRequestView.as_view(), name='leave-request-detail'),
    # Operational Playbook
    path('playbook/tasks/', views.TaskTemplateView.as_view(), name='task-template-list'),
    path('playbook/completions/', views.TaskCompletionView.as_view(), name='task-completion'),
    path('', include(router.urls)),
]

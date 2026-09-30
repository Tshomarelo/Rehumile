from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views, finance_views

router = DefaultRouter()
router.register(r'companies', views.CompanyViewSet, basename='company')
router.register(r'users', views.UserViewSet, basename='user')
router.register(r'incidents', views.IncidentViewSet, basename='incident')
router.register(r'invoices', views.InvoiceViewSet, basename='invoice')

urlpatterns = [
    path('auth/login/', views.LoginView.as_view(), name='login'),
    path('auth/register/', views.RegisterView.as_view(), name='register'),
    path('auth/logout/', views.LogoutView.as_view(), name='logout'),
    path('auth/session/', views.SessionFromTokenView.as_view(), name='auth-session'),
    path('auth/me/', views.MeView.as_view(), name='me'),
    path('auth/password-reset/', views.PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('auth/password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('auth/impersonate/<uuid:user_id>/', views.ImpersonateView.as_view(), name='impersonate'),
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
    # Financial Analytics
    path('financial-analytics/', views.FinancialAnalyticsView.as_view(), name='financial-analytics'),
    # Accounting Engine — Chart of Accounts, Ledger, Expenses, Statements
    path('accounts/', views.ChartOfAccountsView.as_view(), name='account-list'),
    path('accounts/<uuid:pk>/', views.ChartOfAccountsView.as_view(), name='account-detail'),
    path('expenses/', views.ExpenseListView.as_view(), name='expense-list'),
    path('expenses/<uuid:pk>/', views.ExpenseDetailView.as_view(), name='expense-detail'),
    path('ledger/', views.LedgerQueryView.as_view(), name='ledger-query'),
    path('ledger/transactions/<uuid:pk>/', views.LedgerTransactionDetailView.as_view(), name='ledger-transaction-detail'),
    path('reports/income-statement/', views.IncomeStatementView.as_view(), name='income-statement'),
    path('reports/balance-sheet/', views.BalanceSheetView.as_view(), name='balance-sheet'),
    path('reports/cash-flow/', views.CashFlowStatementView.as_view(), name='cash-flow-statement'),
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
    # Website Content Management
    path('website/prices/', views.ServicePriceView.as_view(), name='service-price-list'),
    path('website/prices/<uuid:pk>/', views.ServicePriceView.as_view(), name='service-price-detail'),
    path('website/seed/', views.WebsiteSeedView.as_view(), name='website-seed'),
    path('website/content/', views.WebsiteContentView.as_view(), name='website-content-list'),
    path('website/content/<uuid:pk>/', views.WebsiteContentView.as_view(), name='website-content-detail'),
    # PayFast Payments
    path('payments/initiate/', views.PayFastInitiateView.as_view(), name='payfast-initiate'),
    path('payments/initiate-public/', views.PayFastPublicInitiateView.as_view(), name='payfast-initiate-public'),
    path('payments/payfast-notify/', views.PayFastITNView.as_view(), name='payfast-itn'),
    path('payments/', views.PaymentListView.as_view(), name='payment-list'),
    path('invoices/<uuid:invoice_id>/remind/', views.InvoiceReminderView.as_view(), name='invoice-remind'),
    # Revenue Intelligence — WiFi Subscribers
    path('wifi-subscribers/', views.WifiSubscriberListView.as_view(), name='wifi-subscriber-list'),
    path('wifi-subscribers/<uuid:pk>/', views.WifiSubscriberDetailView.as_view(), name='wifi-subscriber-detail'),
    # Revenue Intelligence — SLA Contracts
    path('sla-contracts/', views.SLAContractListView.as_view(), name='sla-contract-list'),
    path('sla-contracts/<uuid:pk>/', views.SLAContractDetailView.as_view(), name='sla-contract-detail'),
    # Revenue Intelligence — Settings & Auto-invoicing
    path('revenue-allocation/', views.RevenueAllocationView.as_view(), name='revenue-allocation'),
    path('billing/generate-monthly/', views.GenerateMonthlyInvoicesView.as_view(), name='generate-monthly'),
    # Revenue Intelligence — Dashboard
    path('revenue-intelligence/', views.RevenueIntelligenceView.as_view(), name='revenue-intelligence'),
    path('revenue-intelligence/monthly/', views.RevenueMonthlyView.as_view(), name='revenue-monthly'),
    # Company Settings (banking details, contact info)
    path('company-settings/', views.CompanySettingsView.as_view(), name='company-settings'),
    # Invoice print detail
    path('invoices/<uuid:pk>/print/', views.InvoicePrintView.as_view(), name='invoice-print'),
    # Integrated finance: dashboard summary/trend, expense categories, quotations
    path('finance/summary/', finance_views.FinanceSummaryView.as_view(), name='finance-summary'),
    path('finance/trend/', finance_views.FinanceTrendView.as_view(), name='finance-trend'),
    path('expense-categories/', finance_views.ExpenseCategoryView.as_view(), name='expense-category-list'),
    path('expense-categories/<uuid:pk>/', finance_views.ExpenseCategoryView.as_view(), name='expense-category-detail'),
    path('quotations/', finance_views.QuotationListView.as_view(), name='quotation-list'),
    path('quotations/<uuid:pk>/', finance_views.QuotationDetailView.as_view(), name='quotation-detail'),
    path('quotations/<uuid:pk>/action/', finance_views.QuotationActionView.as_view(), name='quotation-action'),
    path('', include(router.urls)),
]

"""
Django Admin Configuration for IMS Models
Provides comprehensive admin interface for system management.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Count, Q
from django.utils.html import format_html
from .models import (
    Company, User, UserProfile, Incident, IncidentComment, IncidentAttachment,
    IncidentTimeline, SLABreach, SLAConfig, Invoice, InvoiceItem, InvoicePayment, Notification,
    AuditLog, DashboardMetric, CompanyBillingInfo,
    Account, ExpenseCategory, Expense, Quotation, QuotationItem,
)


# ============================================================================
# CUSTOM ADMIN FILTERS
# ============================================================================

class SLAStatusFilter(admin.SimpleListFilter):
    """Filter incidents by SLA status"""
    title = 'SLA Status'
    parameter_name = 'sla_status'
    
    def lookups(self, request, model_admin):
        return [
            ('breached', 'Breached'),
            ('at_risk', 'At Risk'),
            ('ok', 'OK'),
        ]
    
    def queryset(self, request, queryset):
        if self.value() == 'breached':
            return queryset.filter(is_sla_breached=True)
        elif self.value() == 'at_risk':
            # At risk: within 2 hours of deadline
            from django.utils import timezone
            from datetime import timedelta
            now = timezone.now()
            two_hours_later = now + timedelta(hours=2)
            return queryset.filter(
                resolution_deadline__gte=now,
                resolution_deadline__lte=two_hours_later,
                status__in=['open', 'in_progress']
            )


class ActiveStatusFilter(admin.SimpleListFilter):
    """Filter by active/inactive status"""
    title = 'Status'
    parameter_name = 'status'
    
    def lookups(self, request, model_admin):
        return [
            ('active', 'Active'),
            ('inactive', 'Inactive'),
        ]
    
    def queryset(self, request, queryset):
        if self.value() == 'active':
            return queryset.filter(status='active')
        elif self.value() == 'inactive':
            return queryset.filter(status='inactive')


# ============================================================================
# INLINE ADMINS
# ============================================================================

class UserProfileInline(admin.StackedInline):
    """Inline admin for UserProfile"""
    model = UserProfile
    extra = 0
    fields = ('phone_number', 'job_title', 'department', 'is_available', 'expertise_areas')


class IncidentCommentInline(admin.TabularInline):
    """Inline comments for incidents"""
    model = IncidentComment
    extra = 0
    readonly_fields = ('author', 'created_at', 'is_internal')
    fields = ('author', 'comment_text', 'is_internal', 'created_at')


class IncidentAttachmentInline(admin.TabularInline):
    """Inline attachments for incidents"""
    model = IncidentAttachment
    extra = 0
    readonly_fields = ('uploaded_by', 'created_at', 'file_size')
    fields = ('file_name', 'file_path', 'file_size', 'uploaded_by', 'created_at')


class InvoiceItemInline(admin.TabularInline):
    """Inline items for invoices"""
    model = InvoiceItem
    extra = 1
    fields = ('description', 'item_type', 'quantity', 'unit_price', 'amount')


class InvoicePaymentInline(admin.TabularInline):
    """Inline payment history for invoices (full or partial payments)"""
    model = InvoicePayment
    extra = 0
    fields = ('amount', 'payment_date', 'payment_method', 'notes', 'recorded_by')
    readonly_fields = ('recorded_by',)


class CompanyBillingInfoInline(admin.StackedInline):
    """Inline billing info for companies"""
    model = CompanyBillingInfo
    extra = 0
    fields = ('billing_frequency', 'hourly_rate', 'incident_fee', 'tax_rate', 'payment_terms_days')


# ============================================================================
# MAIN ADMIN CLASSES
# ============================================================================

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'sla_type', 'status', 'user_count', 'incident_count', 'created_at')
    list_filter = (ActiveStatusFilter, 'sla_type', 'created_at')
    search_fields = ('name', 'contact_email', 'billing_email')
    readonly_fields = ('id', 'created_at', 'updated_at')
    inlines = [CompanyBillingInfoInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'name', 'slug', 'description')
        }),
        ('Contact Information', {
            'fields': ('contact_person', 'contact_email', 'contact_phone')
        }),
        ('Billing Information', {
            'fields': ('billing_email', 'billing_address', 'billing_city', 'billing_state', 
                      'billing_postal_code', 'billing_country')
        }),
        ('Service Configuration', {
            'fields': ('sla_type', 'status', 'is_deleted')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def user_count(self, obj):
        """Display user count per company"""
        count = obj.users.filter(status='active').count()
        return format_html(f'<b>{count}</b> users')
    user_count.short_description = 'Users'
    
    def incident_count(self, obj):
        """Display incident count per company"""
        count = obj.incidents.filter(status__in=['open', 'in_progress']).count()
        return format_html(f'<b>{count}</b> open')
    incident_count.short_description = 'Open Incidents'


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'first_name', 'role', 'company_display', 'status', 'last_login')
    list_filter = ('role', 'status', 'company', 'created_at')
    search_fields = ('email', 'first_name', 'last_name', 'company__name')
    readonly_fields = ('id', 'last_login', 'created_at', 'updated_at')
    inlines = [UserProfileInline]
    
    fieldsets = (
        ('Authentication', {
            'fields': ('id', 'email', 'password')
        }),
        ('Personal Information', {
            'fields': ('first_name', 'last_name')
        }),
        ('Role & Permissions', {
            'fields': ('role', 'company', 'custom_permissions', 'is_active')
        }),
        ('Account Status', {
            'fields': ('status', 'last_login', 'created_at', 'updated_at')
        }),
    )
    
    def company_display(self, obj):
        """Display company name"""
        if obj.company:
            return obj.company.name
        return format_html('<span style="color: #0066cc;">HQ Admin</span>')
    company_display.short_description = 'Company'


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ('ticket_id', 'title_short', 'company', 'priority', 'status', 
                   'sla_indicator', 'assigned_to_display', 'created_at')
    list_filter = (SLAStatusFilter, 'priority', 'status', 'category', 'company', 'created_at')
    search_fields = ('ticket_id', 'title', 'description', 'company__name')
    readonly_fields = ('id', 'ticket_id', 'created_at', 'updated_at', 'sla_breach_date')
    inlines = [IncidentCommentInline, IncidentAttachmentInline]
    
    fieldsets = (
        ('Ticket Information', {
            'fields': ('id', 'ticket_id', 'title', 'description', 'category')
        }),
        ('Assignment & Status', {
            'fields': ('company', 'submitted_by', 'assigned_to', 'status', 'priority')
        }),
        ('SLA Management', {
            'fields': ('sla_type', 'response_deadline', 'resolution_deadline', 
                      'is_sla_breached', 'sla_breach_date')
        }),
        ('Billing', {
            'fields': ('is_billable', 'hours_worked', 'billable_amount')
        }),
        ('Resolution', {
            'fields': ('resolution_notes', 'resolved_at')
        }),
        ('Escalation', {
            'fields': ('is_escalated', 'escalation_reason', 'escalated_at', 'escalated_to'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def title_short(self, obj):
        """Display truncated title"""
        return obj.title[:50] + '...' if len(obj.title) > 50 else obj.title
    title_short.short_description = 'Title'
    
    def sla_indicator(self, obj):
        """Visual SLA status indicator"""
        if obj.is_sla_breached:
            return format_html('<span style="color: red;">●</span> Breached')
        elif obj.status in ['resolved', 'closed']:
            return format_html('<span style="color: green;">●</span> Closed')
        return format_html('<span style="color: orange;">●</span> Active')
    sla_indicator.short_description = 'SLA Status'
    
    def assigned_to_display(self, obj):
        """Display assigned agent"""
        if obj.assigned_to:
            return obj.assigned_to.email
        return format_html('<span style="color: #999;">Unassigned</span>')
    assigned_to_display.short_description = 'Assigned To'


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'company', 'billing_period_display', 'total_amount', 
                   'status', 'payment_status', 'created_at')
    list_filter = ('status', 'company', 'billing_period_start', 'created_at')
    search_fields = ('invoice_number', 'company__name')
    readonly_fields = ('id', 'invoice_number', 'created_at', 'updated_at', 'sent_at', 'amount_paid')
    inlines = [InvoiceItemInline, InvoicePaymentInline]

    fieldsets = (
        ('Invoice Information', {
            'fields': ('id', 'invoice_number', 'company')
        }),
        ('Billing Period', {
            'fields': ('billing_period_start', 'billing_period_end')
        }),
        ('Financial Details', {
            'fields': ('subtotal', 'tax_rate', 'tax_amount', 'total_amount', 'amount_paid')
        }),
        ('Summary', {
            'fields': ('ticket_count', 'hours_worked')
        }),
        ('Status & Payment', {
            'fields': ('status', 'due_date', 'payment_date', 'sent_at')
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_formset(self, request, form, formset, change):
        # amount = quantity x price, and the invoice subtotal follows the items
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for it in instances:
            if isinstance(it, InvoiceItem):
                it.amount = round(it.quantity * it.unit_price, 2)
            it.save()
        formset.save_m2m()
        inv = form.instance
        if inv.items.exists():
            from decimal import Decimal
            inv.subtotal = sum((i.amount for i in inv.items.all()), Decimal('0'))
            inv.tax_amount = (inv.subtotal * inv.tax_rate / 100).quantize(Decimal('0.01'))
            inv.total_amount = inv.subtotal + inv.tax_amount
            inv.save()

    def billing_period_display(self, obj):
        """Display billing period"""
        return f"{obj.billing_period_start} to {obj.billing_period_end}"
    billing_period_display.short_description = 'Billing Period'
    
    def payment_status(self, obj):
        """Display payment status with color"""
        colors = {
            'draft': '#999',
            'sent': '#ff6600',
            'paid': '#00aa00',
            'overdue': '#cc0000',
            'cancelled': '#cccccc',
        }
        color = colors.get(obj.status, '#999')
        return format_html(f'<span style="color: {color};">●</span> {obj.get_status_display()}')
    payment_status.short_description = 'Payment Status'


@admin.register(SLAConfig)
class SLAConfigAdmin(admin.ModelAdmin):
    list_display = ('sla_type', 'response_time_hours', 'resolution_time_hours', 'availability')
    readonly_fields = ('id', 'created_at', 'updated_at')
    
    fieldsets = (
        ('SLA Configuration', {
            'fields': ('id', 'sla_type')
        }),
        ('Response Times', {
            'fields': ('response_time_hours', 'resolution_time_hours')
        }),
        ('Availability', {
            'fields': ('available_24_7', 'business_hours_start', 'business_hours_end')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def availability(self, obj):
        """Display availability"""
        if obj.available_24_7:
            return '24/7'
        return f"{obj.business_hours_start} - {obj.business_hours_end}"
    availability.short_description = 'Available'


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'notification_type', 'title_short', 'read_status', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = ('user__email', 'title', 'message')
    readonly_fields = ('id', 'created_at', 'read_at')
    
    def title_short(self, obj):
        """Display truncated title"""
        return obj.title[:40] + '...' if len(obj.title) > 40 else obj.title
    title_short.short_description = 'Title'
    
    def read_status(self, obj):
        """Display read status"""
        if obj.is_read:
            return format_html('<span style="color: green;">✓ Read</span>')
        return format_html('<span style="color: red;">✗ Unread</span>')
    read_status.short_description = 'Status'


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'model_name', 'object_id', 'ip_address', 'created_at')
    list_filter = ('action', 'model_name', 'created_at')
    search_fields = ('user__email', 'object_id')
    readonly_fields = ('id', 'old_values', 'new_values', 'created_at')
    
    fieldsets = (
        ('Change Information', {
            'fields': ('id', 'user', 'action', 'model_name', 'object_id')
        }),
        ('Changes', {
            'fields': ('old_values', 'new_values')
        }),
        ('Request Info', {
            'fields': ('ip_address', 'user_agent')
        }),
        ('Timestamp', {
            'fields': ('created_at',)
        }),
    )


@admin.register(DashboardMetric)
class DashboardMetricAdmin(admin.ModelAdmin):
    list_display = ('metric_name', 'company', 'metric_date', 'metric_value_display')
    list_filter = ('metric_name', 'company', 'metric_date')
    readonly_fields = ('id', 'metric_value')
    
    def metric_value_display(self, obj):
        """Display metric value"""
        return str(obj.metric_value)[:50] + '...' if len(str(obj.metric_value)) > 50 else str(obj.metric_value)
    metric_value_display.short_description = 'Value'


# ============================================================================
# FINANCE & REVENUE ADMIN
# ============================================================================

from .models import (
    WifiSubscriber, SLAContract, Subscription, RevenueAllocation,
    Account, LedgerTransaction, LedgerEntry, Expense,
    CashTransaction, ShiftLog, PurchaseSlip, Payment,
    Employee, PayrollEntry, CompanySettings,
)


@admin.register(InvoicePayment)
class InvoicePaymentAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'amount', 'payment_date', 'payment_method', 'recorded_by', 'created_at')
    list_filter = ('payment_method', 'payment_date')
    search_fields = ('invoice__invoice_number', 'notes')
    readonly_fields = ('id', 'created_at')


@admin.register(WifiSubscriber)
class WifiSubscriberAdmin(admin.ModelAdmin):
    list_display = ('client_name', 'axxess_id', 'retail_price', 'wholesale_cost', 'billing_day', 'status')
    list_filter = ('status',)
    search_fields = ('client_name', 'axxess_id', 'contact_email')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(SLAContract)
class SLAContractAdmin(admin.ModelAdmin):
    list_display = ('client_name', 'monthly_retainer', 'contract_start', 'contract_end', 'billing_day', 'status')
    list_filter = ('status',)
    search_fields = ('client_name', 'contact_email')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('client_name', 'company', 'site', 'service_type', 'description', 'quantity', 'unit_price', 'unit_cost', 'billing_day', 'status')
    list_filter = ('service_type', 'status')
    search_fields = ('client_name', 'description', 'contact_email', 'company__name')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(RevenueAllocation)
class RevenueAllocationAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'reinvestment_pct', 'opex_pct', 'owner_pct', 'updated_at')


class LedgerEntryInline(admin.TabularInline):
    model = LedgerEntry
    extra = 0
    can_delete = False
    readonly_fields = ('account', 'debit', 'credit', 'memo')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(LedgerTransaction)
class LedgerTransactionAdmin(admin.ModelAdmin):
    """Read-only: the journal is append-only and only ims/ledger.py may write
    it. Corrections are made by posting reversing entries, never by editing."""
    list_display = ('transaction_date', 'description', 'source_model', 'source_id', 'cash_flow_stream', 'created_by')
    list_filter = ('cash_flow_stream', 'source_model', 'transaction_date')
    search_fields = ('description', 'source_id')
    inlines = [LedgerEntryInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    """Read-only — see LedgerTransactionAdmin."""
    list_display = ('transaction', 'account', 'debit', 'credit', 'memo')
    list_filter = ('account',)
    search_fields = ('memo', 'transaction__description')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CashTransaction)
class CashTransactionAdmin(admin.ModelAdmin):
    list_display = ('description', 'amount', 'payment_method', 'transaction_category', 'cash_flow_stream', 'performed_by', 'created_at')
    list_filter = ('payment_method', 'transaction_category', 'cash_flow_stream')
    search_fields = ('description',)
    readonly_fields = ('id', 'created_at')


@admin.register(ShiftLog)
class ShiftLogAdmin(admin.ModelAdmin):
    list_display = ('date', 'opened_by', 'opening_float', 'closed_by', 'system_total', 'variance', 'is_closed')
    list_filter = ('is_closed', 'date')
    readonly_fields = ('id',)


@admin.register(PurchaseSlip)
class PurchaseSlipAdmin(admin.ModelAdmin):
    list_display = ('supplier_name', 'amount', 'purchase_date', 'cash_flow_stream', 'uploaded_by')
    list_filter = ('cash_flow_stream', 'purchase_date')
    search_fields = ('supplier_name', 'reference_number')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('reference', 'amount', 'item_name', 'status', 'invoice', 'created_at')
    list_filter = ('status',)
    search_fields = ('reference', 'pf_payment_id', 'item_name', 'email_address')
    readonly_fields = ('id', 'raw_itn', 'created_at', 'updated_at')


@admin.register(PayrollEntry)
class PayrollEntryAdmin(admin.ModelAdmin):
    list_display = ('employee', 'compliance_period', 'total_gross', 'paye_amount', 'net_pay', 'is_frozen')
    list_filter = ('is_frozen',)
    readonly_fields = ('id', 'calculated_at')


@admin.register(CompanySettings)
class CompanySettingsAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'phone', 'email')


# Custom Admin Site Configuration
admin.site.site_header = "Rehumile Portal IMS Administration"
admin.site.site_title = "IMS Admin"
admin.site.index_title = "Welcome to IMS Administration"



# ============================================================================
# FINANCE: CHART OF ACCOUNTS, EXPENSE CATEGORIES, EXPENSES, QUOTATIONS
# ============================================================================

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    """An account is a labelled bucket in your books (Rent, Bank, Sales...). Expense categories post into one."""
    list_display = ('code', 'name', 'account_type', 'account_subtype', 'normal_balance', 'is_active', 'is_system')
    list_filter = ('account_type', 'is_active', 'is_system')
    search_fields = ('code', 'name')
    readonly_fields = ('normal_balance',)

    def get_readonly_fields(self, request, obj=None):
        # system accounts are looked up by system_key by the posting code: never rename the key
        return ('system_key', 'is_system', 'normal_balance') if obj else ('normal_balance',)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.normal_balance = 'debit' if obj.account_type in ('asset', 'expense') else 'credit'
            if not obj.system_key:
                obj.system_key = f"CUSTOM_{obj.code}"
        super().save_model(request, obj, form, change)

    def get_fields(self, request, obj=None):
        fields = ['code', 'name', 'description', 'account_type', 'account_subtype', 'is_active']
        return fields + ['system_key', 'is_system', 'normal_balance'] if obj else fields


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'account', 'monthly_budget', 'is_active', 'is_system')
    list_filter = ('kind', 'is_active')
    search_fields = ('name',)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('expense_date', 'vendor', 'expense_category', 'amount', 'payment_status', 'quotation')
    list_filter = ('payment_status', 'category', 'expense_category')
    search_fields = ('vendor', 'description')
    date_hierarchy = 'expense_date'
    readonly_fields = ('recorded_by',)


class QuotationItemInline(admin.TabularInline):
    model = QuotationItem
    extra = 1
    fields = ('description', 'quantity', 'unit_price', 'unit_cost', 'cost_category')


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ('quote_number', 'client_name', 'status', 'issue_date', 'total_amount')
    list_filter = ('status',)
    search_fields = ('quote_number', 'client_name')
    inlines = [QuotationItemInline]
    readonly_fields = ('subtotal', 'tax_amount', 'total_amount', 'estimated_cost')

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.recalculate()


# ── Catch-all: register every remaining ims model with a default admin so
#    nothing (present or future) is ever missing from the admin site. ─────────
from django.apps import apps as django_apps

for _model in django_apps.get_app_config('ims').get_models():
    try:
        admin.site.register(_model)
    except admin.sites.AlreadyRegistered:
        pass

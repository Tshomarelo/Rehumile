from django.contrib import admin

from . import models


class ReadOnlyAdmin(admin.ModelAdmin):
    """Audit entries are append-only: visible, never editable or deletable."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ('timestamp', 'username', 'action', 'module', 'object_repr', 'ip_address')
    list_filter = ('module', 'action', 'sensitive')
    search_fields = ('username', 'object_repr', 'action')


admin.site.register([
    models.Company, models.Site, models.Department, models.Position, models.CostCentre,
    models.Employee, models.EmploymentRecord, models.RoleAssignment,
    models.WorkflowDefinition, models.Delegation, models.Notification,
    models.LeaveType, models.LeavePolicy, models.PublicHoliday, models.BlackoutPeriod,
    models.LeaveTransaction, models.LeaveRequest,
])

from rest_framework.permissions import BasePermission


class IsHQAdmin(BasePermission):
    """Only HQ Administrators can access this endpoint."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == 'admin'
        )


class IsHQAdminOrAgent(BasePermission):
    """HQ Administrators and Support Agents can access this endpoint."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in ('admin', 'agent')
        )


class IsHQAdminOrReadOnly(BasePermission):
    """HQ Administrators can mutate; authenticated users can read."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return request.user.role == 'admin'

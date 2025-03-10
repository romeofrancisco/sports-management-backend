from rest_framework.permissions import BasePermission

class IsAdminUser(BasePermission):
    """Allows access only to Admin users (or superusers)."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_admin

class IsCoachUser(BasePermission):
    """Allows access only to Coach users."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_coach

class IsAdminOrCoachUser(BasePermission):
    """Allows access to Admin or Coach users."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.is_admin or request.user.is_coach
        )
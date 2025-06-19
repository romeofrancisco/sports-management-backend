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

class CanManageGamePermission(BasePermission):
    """
    Custom permission to check if user can manage (start/score/edit) a specific game.
    
    Rules:
    - Admins can manage any game (practice, league, tournament)
    - For league games: Only coaches explicitly assigned to the game can manage it
    - For practice games: Coaches can manage games for their own teams
    """
    
    def has_permission(self, request, view):
        # Must be authenticated and either admin or coach
        return request.user.is_authenticated and (
            request.user.is_admin or request.user.is_coach
        )
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        
        # Use the game's has_coach_permission method which handles all permission logic
        return obj.has_coach_permission(user)

class CanCreateGamePermission(BasePermission):
    """
    Custom permission to check if user can create games.
    
    Rules:
    - Admins can create any type of game
    - Coaches can only create practice games for their own teams
    """
    
    def has_permission(self, request, view):
        # Must be authenticated and either admin or coach
        return request.user.is_authenticated and (
            request.user.is_admin or request.user.is_coach
        )
    
    def has_object_permission(self, request, view, obj):
        # This is handled in the view's perform_create method
        return self.has_permission(request, view)
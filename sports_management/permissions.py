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
    - Coaches can only manage practice games for their own teams
    - Coaches cannot manage league or tournament games
    """
    
    def has_permission(self, request, view):
        # Must be authenticated and either admin or coach
        return request.user.is_authenticated and (
            request.user.is_admin or request.user.is_coach
        )
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        
        # Admins can manage any game
        if user.is_admin:
            return True
        
        # For coaches, check game type and team ownership
        if user.is_coach and hasattr(user, 'coach_profile'):
            # Only allow practice games
            if obj.type != 'normal':  # 'normal' maps to practice games in the model
                return False
            
            # Check if coach owns either team in the game
            coach_teams = list(user.coach_profile.teams.all())
            return (obj.home_team in coach_teams or obj.away_team in coach_teams)
        
        # Deny access for other users
        return False

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
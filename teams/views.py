from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.decorators import action
from .serializers import PlayerInfoSerializer, CoachInfoSerializer, TeamSerializer
from .models import Player, Coach, Team
from sports.models import Sport
from rest_framework.permissions import IsAuthenticated
from sports_management.permissions import IsAdminUser, IsCoachUser, IsAdminOrCoachUser
from rest_framework.response import Response
from rest_framework import status
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import F
from .filters import CoachFilter, PlayerFilter
from rest_framework.pagination import PageNumberPagination
from django.core.exceptions import PermissionDenied


class Pagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50


class TeamViewSet(ModelViewSet):
    queryset = Team.objects.all()
    lookup_field = "slug"
    serializer_class = TeamSerializer
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["name"]
    filterset_fields = ["sport", "division"]
    pagination_class = Pagination
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context
    def get_queryset(self):
        """
        Return teams based on user role:
        - Admin: All teams
        - Coach: Only their own teams
        - Player: Only their team
        - Others: Permission denied for all actions including list
        """
        user = self.request.user
        
        # For admins, show all teams with optimized queries
        if user.is_admin:
            return Team.objects.select_related('sport', 'coach__user').prefetch_related('players')
              # For coaches, show only their teams with optimized queries
        if hasattr(user, 'coach_profile'):
            return user.coach_profile.teams.select_related('sport', 'coach__user').prefetch_related('players')
            
        # For players, show only their team with optimized queries
        if hasattr(user, 'player_profile') and user.player_profile.team:
            return Team.objects.select_related('sport', 'coach__user').prefetch_related('players').filter(id=user.player_profile.team.id)
            
        # User doesn't have appropriate role - deny access
        raise PermissionDenied("You don't have permission to access team data")

    def get_object(self):
        # Store the unfiltered queryset
        unfiltered_queryset = Team.objects.all()
        
        # Get the filtered queryset based on user role
        filtered_queryset = self.filter_queryset(self.get_queryset())

        # Get the lookup value from the URL
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs[lookup_url_kwarg]

        # Try to determine if the lookup value is a numeric ID
        try:
            is_numeric = lookup_value.isdigit()
        except (AttributeError, ValueError):
            is_numeric = False

        if is_numeric:
            # If it's numeric, look up by ID
            filter_kwargs = {"pk": lookup_value}
        else:
            # Otherwise, use slug
            filter_kwargs = {self.lookup_field: lookup_value}

        # First check if the object exists at all in the unfiltered queryset
        try:
            obj = unfiltered_queryset.get(**filter_kwargs)
        except Team.DoesNotExist:
            # If the team doesn't exist at all, raise 404
            from django.http import Http404
            raise Http404("Team does not exist")
        
        # Now check if the object is in the filtered queryset (user has access)
        if not filtered_queryset.filter(**filter_kwargs).exists():
            # If the team exists but user doesn't have access, raise permission denied
            raise PermissionDenied("You don't have permission to access this team")
        
        # Get the object from the filtered queryset
        obj = filtered_queryset.get(**filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj
    
    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to anyone
        - DELETE requests are restricted to admin users
        - POST/PUT requests can be done by admins or coaches
        - Coaches can modify their own teams
        """
        if self.action in ['create', 'update', 'destroy', 'partial_update']:
            permission_classes = [IsAdminOrCoachUser]
        elif self.action in ['my_team', 'my_team_players', 'my_teammates']:
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = []
            
        return [permission() for permission in permission_classes]
    
    def perform_create(self, serializer):
        """
        When a coach creates a team, automatically assign the coach to the team
        """
        # If the requesting user is a coach, set them as the team's coach
        if self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            coach = self.request.user.coach_profile
            team = serializer.save(coach=coach)  # Direct assignment
        else:
            team = serializer.save()
            
        return team

    def perform_update(self, serializer):
        """Only allow coaches to update their own teams"""
        if self.request.user.is_admin:
            # Admins can update any team
            serializer.save()
        elif self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            # Coaches can only update their own teams
            coach_teams = self.request.user.coach_profile.teams.all()
            if serializer.instance in coach_teams:
                serializer.save()
            else:
                raise PermissionDenied("You can only update your own teams")    
    
    def perform_destroy(self, instance):
        """Only allow coaches to delete their own teams"""
        if self.request.user.is_admin:
            # Admins can delete any team
            instance.delete()
        elif self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            # Coaches can only delete their own teams
            coach = self.request.user.coach_profile
            coach_teams = list(coach.teams.all())
            
            # Check if the team belongs to the coach
            if instance in coach_teams:
                instance.delete()
            else:
                raise PermissionDenied("You can only delete your own teams")
    
    @action(detail=True, methods=["get"], get_permissions=[IsAdminUser])
    def coaches(self, request, **kwargs):
        team = self.get_object()
        coaches = team.coach.all()
        serializer = CoachInfoSerializer(coaches, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"], get_permissions=[IsAdminOrCoachUser])
    def players(self, request, **kwargs):
        team = self.get_object()
        players = team.players.select_related("user").all()
        serializer = PlayerInfoSerializer(players, many=True, context={'request': request})
        return Response(serializer.data)


    
class SportTeamsViewSet(ReadOnlyModelViewSet):
    serializer_class = TeamSerializer
    lookup_field = "pk"
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        sport_slug = self.kwargs["sport_slug"]
        try:
            sport = Sport.objects.get(slug=sport_slug)
            return Team.objects.filter(sport=sport)
        except Sport.DoesNotExist:
            return Response(
                {"error": "Sport does not exist"}, status=status.HTTP_404_NOT_FOUND
            )


class PlayerViews(ModelViewSet):
    queryset = Player.objects.all()
    serializer_class = PlayerInfoSerializer
    lookup_field = "slug"
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["first_name", "last_name"]
    filterset_class = PlayerFilter
    pagination_class = Pagination
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context
 
    def get_queryset(self):
        """
        Return players based on user role:
        - Admin: All players
        - Coach: Only players on their teams
        - Player: Only teammates
        - Others: Permission denied for all actions including list
        """
        user = self.request.user
        
        # Base queryset with annotations
        base_queryset = Player.objects.select_related("user").annotate(
            first_name=F("user__first_name"),
            last_name=F("user__last_name"),
            sex=F("user__sex"),
        ).order_by("user__first_name")
        
        # For admins, show all players
        if user.is_admin:
            return base_queryset
            
        # For coaches, show only players from their teams
        if hasattr(user, 'coach_profile'):
            coach_teams = user.coach_profile.teams.all()
            return base_queryset.filter(team__in=coach_teams)
            
        # For players, show only teammates
        if hasattr(user, 'player_profile') and user.player_profile.team:
            player_team = user.player_profile.team
            return base_queryset.filter(team=player_team)
            
        # User doesn't have appropriate role - deny access
        raise PermissionDenied("You don't have permission to access player data")
    
    def get_object(self):
        """
        Similar to TeamViewSet.get_object, this ensures players can only be accessed
        based on user role permissions
        """
        # Store the unfiltered queryset
        unfiltered_queryset = Player.objects.all()
        
        # Get the filtered queryset based on user role
        filtered_queryset = self.filter_queryset(self.get_queryset())

        # Get the lookup value from the URL
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs[lookup_url_kwarg]

        # Try to determine if the lookup value is a numeric ID
        try:
            is_numeric = lookup_value.isdigit()
        except (AttributeError, ValueError):
            is_numeric = False

        if is_numeric:
            # If it's numeric, look up by ID
            filter_kwargs = {"pk": lookup_value}
        else:
            # Otherwise, use slug
            filter_kwargs = {self.lookup_field: lookup_value}

        # First check if the object exists at all in the unfiltered queryset
        try:
            obj = unfiltered_queryset.get(**filter_kwargs)
        except Player.DoesNotExist:
            # If the player doesn't exist at all, raise 404
            from django.http import Http404
            raise Http404("Player does not exist")
        
        # Now check if the object is in the filtered queryset (user has access)
        if not filtered_queryset.filter(**filter_kwargs).exists():
            # If the player exists but user doesn't have access, raise permission denied
            raise PermissionDenied("You don't have permission to access this player")
        
        # Get the object from the filtered queryset
        obj = filtered_queryset.get(**filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj
    
    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        - GET requests are accessible to anyone with proper role (filtered by get_queryset)
        - POST/CREATE requests are restricted to admin users
        - DELETE/UPDATE requests can be done by admins or coaches (with team restrictions)
        - Coaches can only modify players from their own teams
        """
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [IsAdminOrCoachUser]
        else:
            permission_classes = [IsAuthenticated]
            
        return [permission() for permission in permission_classes]
    
    def perform_update(self, serializer):
        """Only allow coaches to update players in their own teams"""
        if self.request.user.is_admin:
            # Admins can update any player
            serializer.save()
        elif self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            # Coaches can only update players from their teams
            coach = self.request.user.coach_profile
            coach_teams = list(coach.teams.all())
            player = serializer.instance
            
            # Make sure player has a team and that team is in coach's teams
            if player.team and any(team.id == player.team.id for team in coach_teams):
                serializer.save()
            else:
                raise PermissionDenied("You can only update players from your own teams")
    
    def perform_destroy(self, instance):
        """Only allow coaches to delete players in their own teams"""
        if self.request.user.is_admin:
            # Admins can delete any player
            instance.delete()
        elif self.request.user.is_coach and hasattr(self.request.user, 'coach_profile'):
            # Coaches can only delete players from their teams
            coach = self.request.user.coach_profile
            coach_teams = list(coach.teams.all())
            player = instance
            
            # Make sure player has a team and that team is in coach's teams
            if player.team and any(team.id == player.team.id for team in coach_teams):
                instance.delete()
            else:
                raise PermissionDenied("You can only delete players from your own teams")


class CoachViews(ModelViewSet):
    queryset = Coach.objects.all().prefetch_related("team_set")
    serializer_class = CoachInfoSerializer
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["first_name", "last_name"]
    filterset_class = CoachFilter
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        return Coach.objects.select_related("user").annotate(
            first_name=F("user__first_name"),
            last_name=F("user__last_name"),
            sex=F("user__sex"),
        )

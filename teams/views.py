from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.decorators import action
from .serializers import PlayerInfoSerializer, CoachInfoSerializer, TeamSerializer, GameSummarySerializer
from .models import Player, Coach, Team
from sports.models import Sport
from rest_framework.permissions import IsAuthenticated
from sports_management.permissions import IsAdminUser, IsCoachUser, IsAdminOrCoachUser
from rest_framework.response import Response
from rest_framework import status
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import F, Count, Q, Avg, Sum, Max, Min
from django.db import models
from .filters import CoachFilter, PlayerFilter
from rest_framework.pagination import PageNumberPagination
from django.core.exceptions import PermissionDenied
from datetime import datetime, timedelta
from django.utils import timezone
# Import models and serializers for analytics
from games.models import Game
from games.serializers import GameSerializer
from trainings.models import TrainingSession
from trainings.serializers import TrainingSessionListSerializer


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
        - Others: Permission denied for all actions including list        """
        user = self.request.user
        
        # For admins, show all teams with optimized queries
        if user.is_authenticated and hasattr(user, 'is_admin') and user.is_admin:
            return Team.objects.select_related('sport', 'coach__user').prefetch_related(
                'players', 'coach__sports'
            )
            
        # For coaches, show only their teams with optimized queries
        if hasattr(user, 'coach_profile'):
            return user.coach_profile.teams.select_related('sport', 'coach__user').prefetch_related(
                'players', 'coach__sports'
            )
            
        # For players, show only their team with optimized queries
        if hasattr(user, 'player_profile') and user.player_profile.team:
            return Team.objects.select_related('sport', 'coach__user').prefetch_related(
                'players', 'coach__sports'
            ).filter(id=user.player_profile.team.id)
            
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
    
    @action(detail=True, methods=["get"], permission_classes=[IsAdminUser])
    def coaches(self, request, **kwargs):
        team = self.get_object()
        coaches = team.coach.all()
        serializer = CoachInfoSerializer(coaches, many=True, context={'request': request})
        return Response(serializer.data)    
    
    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def players(self, request, **kwargs):
        team = self.get_object()
        players = team.players.select_related("user").all()
        serializer = PlayerInfoSerializer(players, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def analytics(self, request, **kwargs):
        team = self.get_object()
        
        # Time range filter (default to last 30 days)
        days = int(request.query_params.get('days', 30))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Games analytics
        all_games = Game.objects.filter(
            models.Q(home_team=team) | models.Q(away_team=team)
        )
        recent_games = all_games.filter(date__range=[start_date, end_date])
        
        # Calculate wins, losses, draws
        wins = 0
        losses = 0
        draws = 0
        
        for game in all_games.filter(status=Game.Status.COMPLETED):
            if game.winner_team == team:
                wins += 1
            elif game.winner_team is None:
                draws += 1
            else:
                losses += 1
        
        # Training analytics
        all_trainings = TrainingSession.objects.filter(team=team)
        recent_trainings = all_trainings.filter(date__range=[start_date.date(), end_date.date()])
        
        # Player statistics
        total_players = team.players.count()
        
        analytics_data = {
            "total_games": all_games.count(),
            "recent_games": recent_games.count(),
            "total_wins": wins,
            "total_losses": losses,
            "total_draws": draws,
            "win_rate": round((wins / max(wins + losses + draws, 1)) * 100, 2),
            "total_trainings": all_trainings.count(),
            "recent_trainings": recent_trainings.count(),
            "total_players": total_players,
            "upcoming_games": all_games.filter(
                date__gte=timezone.now(),
                status__in=[Game.Status.SCHEDULED, Game.Status.POSTPONED]
            ).count(),
            "completed_games": all_games.filter(status=Game.Status.COMPLETED).count(),
            "training_completion_rate": self._calculate_training_completion_rate(team),
            "average_attendance": self._calculate_average_attendance(team),
            "time_range_days": days
        }
        return Response(analytics_data)    
    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def performance(self, request, **kwargs):
        team = self.get_object()
        
        # Time range filter (default to last 30 days)
        days = int(request.query_params.get('days', 30))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Get team games for performance analysis
        team_games = Game.objects.filter(
            models.Q(home_team=team) | models.Q(away_team=team),
            status=Game.Status.COMPLETED
        )
        
        # Calculate performance metrics
        if team_games.exists():
            # Calculate average scores
            home_scores = team_games.filter(home_team=team).aggregate(
                avg_score=Avg('home_team_score')
            )['avg_score'] or 0
            
            away_scores = team_games.filter(away_team=team).aggregate(
                avg_score=Avg('away_team_score')
            )['avg_score'] or 0
            
            average_score = (home_scores + away_scores) / 2 if (home_scores or away_scores) else 0
            
            # Get highest scores
            highest_home_score = team_games.filter(home_team=team).aggregate(
                max_score=Max('home_team_score')
            )['max_score'] or 0
            
            highest_away_score = team_games.filter(away_team=team).aggregate(
                max_score=Max('away_team_score')
            )['max_score'] or 0
            
            highest_score = max(highest_home_score, highest_away_score)
        else:
            average_score = 0
            highest_score = 0
        
        # Training performance metrics
        completed_trainings = TrainingSession.objects.filter(
            team=team,
            status=TrainingSession.Status.COMPLETED
        )
        
        performance_data = {
            "average_team_score": round(average_score, 2),
            "highest_game_score": highest_score,
            "total_completed_games": team_games.count(),
            "total_completed_trainings": completed_trainings.count(),
            "recent_performance": self._get_recent_performance_trend(team, start_date),
            "training_effectiveness": self._calculate_training_effectiveness(team),
            "time_range_days": days
        }
        return Response(performance_data)      
    
    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def games(self, request, **kwargs):
        team = self.get_object()
        
        # Get all games for the team (both home and away)
        games = Game.objects.filter(
            models.Q(home_team=team) | models.Q(away_team=team)
        ).select_related('home_team', 'away_team', 'sport', 'league', 'season').order_by('-date')
        
        # Add pagination support
        page = self.paginate_queryset(games)
        if page is not None:
            serializer = GameSummarySerializer(page, many=True, context={'request': request, 'team': team})
            return self.get_paginated_response(serializer.data)
            
        serializer = GameSummarySerializer(games, many=True, context={'request': request, 'team': team})
        return Response(serializer.data)
      
    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def games_all(self, request, **kwargs):
        """
        Non-paginated endpoint to get all team games.
        Used by TeamDetails component for upcoming and recent games sections.
        """
        team = self.get_object()
        
        # Get all games for the team (both home and away)
        games = Game.objects.filter(
            models.Q(home_team=team) | models.Q(away_team=team)
        ).select_related('home_team', 'away_team', 'sport', 'league', 'season').order_by('-date')
        
        # No pagination - return all games
        serializer = GameSummarySerializer(games, many=True, context={'request': request, 'team': team})
        return Response(serializer.data)
    
    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def training_sessions(self, request, **kwargs):
        team = self.get_object()
        
        # Get all training sessions for the team
        trainings = TrainingSession.objects.filter(team=team).select_related(
            'coach', 'coach__user'
        ).prefetch_related('categories').order_by('-date')
        
        # Add pagination support
        page = self.paginate_queryset(trainings)
        if page is not None:
            serializer = TrainingSessionListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
            
        serializer = TrainingSessionListSerializer(trainings, many=True, context={'request': request})
        return Response(serializer.data)    
    
    @action(detail=True, methods=["get"], permission_classes=[IsAdminOrCoachUser])
    def statistics(self, request, **kwargs):
        team = self.get_object()
        
        # Basic team statistics
        total_players = team.players.count()
          # Gender distribution (assuming User model has sex field)
        gender_stats = team.players.values('user__sex').annotate(
            count=Count('*')
        )
        
        gender_distribution = {"male": 0, "female": 0, "other": 0}
        for stat in gender_stats:
            sex = stat['user__sex']
            count = stat['count']
            if sex == 'M':
                gender_distribution['male'] = count
            elif sex == 'F':
                gender_distribution['female'] = count
            else:
                gender_distribution['other'] = count
        
        # Games statistics
        all_games = Game.objects.filter(
            models.Q(home_team=team) | models.Q(away_team=team)
        )
        
        # Calculate game results
        wins = losses = draws = 0
        for game in all_games.filter(status=Game.Status.COMPLETED):
            if game.winner_team == team:
                wins += 1
            elif game.winner_team is None:
                draws += 1
            else:
                losses += 1          # Training statistics
        training_stats = TrainingSession.objects.filter(team=team).aggregate(
            total_sessions=Count('id'),
            completed_sessions=Count('id', filter=models.Q(status=TrainingSession.Status.COMPLETED)),
            upcoming_sessions=Count('id', filter=models.Q(status=TrainingSession.Status.UPCOMING))
        )
        
        statistics_data = {
            "total_players": total_players,
            "gender_distribution": gender_distribution,
            "games_statistics": {
                "total_games": all_games.count(),
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "win_percentage": round((wins / max(wins + losses + draws, 1)) * 100, 2)
            },
            "training_statistics": {
                "total_sessions": training_stats['total_sessions'] or 0,
                "completed_sessions": training_stats['completed_sessions'] or 0,
                "upcoming_sessions": training_stats['upcoming_sessions'] or 0,
                "completion_rate": round(
                    (training_stats['completed_sessions'] / max(training_stats['total_sessions'], 1)) * 100, 2
                )
            },            "activity_summary": {
                "last_game": self._serialize_game(all_games.order_by('-date').first()),
                "next_game": self._serialize_game(all_games.filter(
                    date__gte=timezone.now(),
                    status=Game.Status.SCHEDULED
                ).order_by('date').first()),
                "last_training": self._serialize_training(TrainingSession.objects.filter(
                    team=team,
                    status=TrainingSession.Status.COMPLETED
                ).order_by('-date').first()),
                "next_training": self._serialize_training(TrainingSession.objects.filter(
                    team=team,
                    status=TrainingSession.Status.UPCOMING
                ).order_by('date').first())
            }
        }
        return Response(statistics_data)
    
    def _calculate_training_completion_rate(self, team):
        """Calculate the percentage of training sessions that were completed"""
        total_sessions = TrainingSession.objects.filter(team=team).count()
        completed_sessions = TrainingSession.objects.filter(
            team=team,
            status=TrainingSession.Status.COMPLETED
        ).count()
        
        if total_sessions == 0:
            return 0
        return round((completed_sessions / total_sessions) * 100, 2)
    
    def _calculate_average_attendance(self, team):
        """Calculate average attendance rate for training sessions"""
        from trainings.models import PlayerTraining
        
        completed_sessions = TrainingSession.objects.filter(
            team=team,
            status=TrainingSession.Status.COMPLETED
        )
        
        if not completed_sessions.exists():
            return 0
        
        total_expected_attendance = 0
        total_actual_attendance = 0
        
        for session in completed_sessions:
            expected = team.players.count()
            actual = PlayerTraining.objects.filter(
                session=session,
                attendance_status__in=['present', 'late']  # Count present and late as attended
            ).count()
            
            total_expected_attendance += expected
            total_actual_attendance += actual
        
        if total_expected_attendance == 0:
            return 0
        
        return round((total_actual_attendance / total_expected_attendance) * 100, 2)
      
    def _get_recent_performance_trend(self, team, start_date):
        """Get performance trend for recent games"""
        recent_games = Game.objects.filter(
            models.Q(home_team=team) | models.Q(away_team=team),
            date__gte=start_date,
            status=Game.Status.COMPLETED
        ).order_by('date')
        
        trend_data = []
        for game in recent_games:
            if game.home_team == team:
                team_score = game.home_team_score or 0
                opponent_score = game.away_team_score or 0
            else:
                team_score = game.away_team_score or 0
                opponent_score = game.home_team_score or 0
            
            # Determine result based on scores first, then fall back to winner_team field
            if team_score > opponent_score:
                result = 'win'
            elif team_score < opponent_score:
                result = 'loss'
            elif team_score == opponent_score:
                result = 'draw'
            else:
                # Fallback to winner_team field if scores are unclear
                result = 'win' if game.winner_team == team else ('draw' if game.winner_team is None else 'loss')
            
            trend_data.append({
                'date': game.date.strftime('%Y-%m-%d'),
                'team_score': team_score,
                'opponent_score': opponent_score,
                'result': result
            })
        
        return trend_data
    
    def _calculate_training_effectiveness(self, team):
        """Calculate training effectiveness based on completion and attendance"""
        completion_rate = self._calculate_training_completion_rate(team)
        attendance_rate = self._calculate_average_attendance(team)
        
        # Simple effectiveness score combining completion and attendance
        effectiveness = (completion_rate + attendance_rate) / 2
        return round(effectiveness, 2)

    def _serialize_game(self, game):
        """Serialize a Game object for JSON response"""
        if not game:
            return None
        
        return {
            'id': game.id,
            'home_team': game.home_team.name if game.home_team else None,
            'away_team': game.away_team.name if game.away_team else None,
            'home_team_score': game.home_team_score,
            'away_team_score': game.away_team_score,
            'date': game.date.isoformat() if game.date else None,
            'status': game.status,
            'sport': game.sport.name if game.sport else None,
            'winner_team': game.winner_team.name if game.winner_team else None
        }
    
    def _serialize_training(self, training):
        """Serialize a TrainingSession object for JSON response"""
        if not training:
            return None
        
        return {
            'id': training.id,
            'title': training.title,
            'date': training.date.isoformat() if training.date else None,
            'start_time': training.start_time.isoformat() if training.start_time else None,
            'end_time': training.end_time.isoformat() if training.end_time else None,
            'status': training.status,
            'team': training.team.name if training.team else None,
            'coach': f"{training.coach.user.first_name} {training.coach.user.last_name}" if training.coach and training.coach.user else None
        }

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
    pagination_class = Pagination
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

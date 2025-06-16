from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import models
from .models import PlayerStat
from .serializers import PlayerStatSerializer
from .services.player_improvement_service import PlayerImprovementService, TeamPlayerImprovementService


class PlayerImprovementViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet specifically for player improvement tracking endpoints
    Separate from main PlayerStatViewSet to avoid conflicts
    """
    queryset = PlayerStat.objects.select_related('player', 'game', 'stat_type')
    serializer_class = PlayerStatSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter stats based on user role and permissions"""
        user = self.request.user
        base_queryset = super().get_queryset()
        
        if user.is_admin:
            # Admins can see all stats
            return base_queryset
        elif user.is_coach and hasattr(user, 'coach_profile'):
            # Coaches can see stats for their teams' players
            coach_teams = user.coach_profile.teams.all()
            return base_queryset.filter(player__team__in=coach_teams)
        elif user.is_player and hasattr(user, 'player_profile'):
            # Players can only see their own stats
            return base_queryset.filter(player=user.player_profile)
        
        # Default: no stats visible
        return base_queryset.none()

    @action(detail=False, methods=['get'])
    def game_by_game_improvement(self, request):
        """
        Track improvement for each game compared to previous games
        Query params: player_id, stat_type_code, games_limit (default: 10)
        """
        player_id = request.query_params.get('player_id')
        stat_type_code = request.query_params.get('stat_type_code')
        games_limit = int(request.query_params.get('games_limit', 10))
        
        if not player_id or not stat_type_code:
            return Response(
                {"error": "Both player_id and stat_type_code are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            service = PlayerImprovementService(player_id)
            result = service.get_game_by_game_improvement(stat_type_code, games_limit)
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def running_average_improvement(self, request):
        """
        Track how player performs against their running average
        Query params: player_id, stat_type_code, games_limit (default: 10)
        """
        player_id = request.query_params.get('player_id')
        stat_type_code = request.query_params.get('stat_type_code')
        games_limit = int(request.query_params.get('games_limit', 10))
        
        if not player_id or not stat_type_code:
            return Response(
                {"error": "Both player_id and stat_type_code are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            service = PlayerImprovementService(player_id)
            result = service.get_running_average_improvement(stat_type_code, games_limit)
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def improvement_streak(self, request):
        """
        Get current improvement/decline streak
        Query params: player_id, stat_type_code, max_games (default: 5)
        """
        player_id = request.query_params.get('player_id')
        stat_type_code = request.query_params.get('stat_type_code')
        max_games = int(request.query_params.get('max_games', 5))
        
        if not player_id or not stat_type_code:
            return Response(
                {"error": "Both player_id and stat_type_code are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            service = PlayerImprovementService(player_id)
            result = service.get_improvement_streak(stat_type_code, max_games)
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def multi_stat_improvement(self, request):
        """
        Track improvements across multiple stats for comprehensive analysis
        Query params: player_id, stat_type_codes (comma-separated), games_limit (default: 10)
        """
        player_id = request.query_params.get('player_id')
        stat_type_codes_str = request.query_params.get('stat_type_codes')
        games_limit = int(request.query_params.get('games_limit', 10))
        
        if not player_id or not stat_type_codes_str:
            return Response(
                {"error": "Both player_id and stat_type_codes are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        stat_type_codes = [code.strip() for code in stat_type_codes_str.split(',')]
        
        try:
            service = PlayerImprovementService(player_id)
            result = service.get_multi_stat_improvement(stat_type_codes, games_limit)
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def season_progression(self, request):
        """
        Track player progression throughout a season
        Query params: player_id, stat_type_code, season_id (optional)
        """
        player_id = request.query_params.get('player_id')
        stat_type_code = request.query_params.get('stat_type_code')
        season_id = request.query_params.get('season_id')
        
        if not player_id or not stat_type_code:
            return Response(
                {"error": "Both player_id and stat_type_code are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            service = PlayerImprovementService(player_id)
            result = service.get_season_progression(stat_type_code, season_id)
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def team_improvement_summary(self, request):
        """
        Get improvement summary for all players in a team
        Query params: team_id, stat_type_code, games_limit (default: 5)
        """
        team_id = request.query_params.get('team_id')
        stat_type_code = request.query_params.get('stat_type_code')
        games_limit = int(request.query_params.get('games_limit', 5))
        
        if not team_id or not stat_type_code:
            return Response(
                {"error": "Both team_id and stat_type_code are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            service = TeamPlayerImprovementService(team_id)
            result = service.get_team_improvement_summary(stat_type_code, games_limit)
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

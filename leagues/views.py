# filepath: views_revised.py
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from .models import League, Season
from .serializers import LeagueSerializer, LeagueWriteSerializer, SeasonSerializer, TeamStandingsSerializer, LeagueStatisticsSerializer, SeasonComparisonSerializer
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum, Avg, F, Q, Func
from teams.models import Team
from sports.models import Sport


# Custom pagination class specifically for seasons
class SeasonPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

class LeagueViewSet(viewsets.ModelViewSet):
    queryset = League.objects.select_related('sport').prefetch_related(
        'seasons',
        'seasons__teams',
        'seasons__games'
    )
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return LeagueWriteSerializer
        return LeagueSerializer
    
    @action(detail=True, methods=["get"])
    def standings(self, request, pk=None):
        league = self.get_object()
        standings = league.standings(request=request)
        
        return Response(standings)
    
    @action(detail=True, methods=["get"])
    def statistics(self, request, pk=None):
        """Get comprehensive league statistics for the dashboard"""
        league = self.get_object()
        
        # Basic statistics calculation - can be expanded later
        seasons = league.seasons.all()
        teams_count = Team.objects.filter(leagues__in=seasons).distinct().count()
        seasons_count = seasons.count()
        active_seasons = seasons.filter(status='ongoing').count()
        
        total_games = 0
        for season in seasons:
            total_games += season.games_count
        
        current_season = seasons.filter(status='ongoing').first()
        
        statistics = {
            'teams_count': teams_count,
            'seasons_count': seasons_count,
            'active_seasons': active_seasons,
            'games_count': total_games,
            'current_season': SeasonSerializer(current_season, context={'request': request}).data if current_season else None
        }
        
        return Response(statistics)
    @action(detail=True, methods=["get"])
    def team_form(self, request, pk=None):
        """Get the recent form for top teams in the league"""
        league = self.get_object()
        
        from .services import LeagueStatisticsService
        
        # Get team form data
        stats_service = LeagueStatisticsService(league, request)
        team_form_data = stats_service.get_team_form()
        
        return Response(team_form_data)
    
    @action(detail=True, methods=["get"])
    def comprehensive_stats(self, request, pk=None):
        """Get detailed comprehensive statistics for the entire league"""
        league = self.get_object()
        
        from .services import LeagueStatisticsService
        service = LeagueStatisticsService(league, request)
        stats = service.get_comprehensive_stats()
        
        return Response(stats)
        
    @action(detail=True, methods=["get"])
    def league_leaders(self, request, pk=None):
        """Get the top players across all seasons for each leader category in the league"""
        try:
            league = self.get_object()
            
            from .services import LeagueLeaderService
            service = LeagueLeaderService(league_id=league.id, request=request)
            data = service.get_league_leaders()
            
            return Response(data)
        except Exception as e:
            return Response(
                {"error": f"Failed to get league leaders: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class SeasonViewSet(viewsets.ModelViewSet):
    serializer_class = SeasonSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = SeasonPagination

    def get_queryset(self):
        return Season.objects.filter(league_id=self.kwargs['league_pk'])

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if 'league_pk' in self.kwargs:
            league = get_object_or_404(League, pk=self.kwargs['league_pk'])
            context['league'] = league
        return context

    def perform_create(self, serializer):
        league = get_object_or_404(League, pk=self.kwargs['league_pk'])
        serializer.save(league=league)
    
    @action(detail=True, methods=["post"])
    def manage(self, request, pk=None, **kwargs):
        season = self.get_object()
        action_type = request.data.get("action")
        
        try:
            # Basic season management - can be expanded later
            if action_type == "start":
                season.start_season()
                return Response({"message": "Season started successfully"}, status=status.HTTP_200_OK)
            elif action_type == "complete":
                season.complete_season()
                return Response({"message": "Season completed successfully"}, status=status.HTTP_200_OK)
            elif action_type == "pause":
                season.pause_season()
                return Response({"message": "Season paused successfully"}, status=status.HTTP_200_OK)
            elif action_type == "cancel":
                season.cancel_season()
                return Response({"message": "Season cancelled successfully"}, status=status.HTTP_200_OK)
            else:
                return Response({"error": "Invalid action"}, status=status.HTTP_400_BAD_REQUEST)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def add_team(self, request, pk=None):
        season = self.get_object()
        team_id = request.data.get('team_id')
        
        try:
            team = get_object_or_404(Team, pk=team_id)
            
            # Validate team division matches league division
            if team.division != season.league.division:
                return Response({
                    'error': f"Team '{team.name}' has division '{team.division}' but league '{season.league.name}' requires '{season.league.division}' division."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if team is already in the season
            if season.teams.filter(id=team_id).exists():
                return Response({
                    'error': f"Team '{team.name}' is already in this season."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            season.teams.add(team)
            return Response({
                'message': f"Team '{team.name}' added to season successfully."
            }, status=status.HTTP_200_OK)
            
        except Team.DoesNotExist:
            return Response({
                'error': 'Team not found.'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def remove_team(self, request, pk=None):
        season = self.get_object()
        team_id = request.data.get('team_id')
        
        try:
            team = get_object_or_404(Team, pk=team_id)
            
            # Check if team is in the season
            if not season.teams.filter(id=team_id).exists():
                return Response({
                    'error': f"Team '{team.name}' is not in this season."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            season.teams.remove(team)
            return Response({
                'message': f"Team '{team.name}' removed from season successfully."
            }, status=status.HTTP_200_OK)
            
        except Team.DoesNotExist:
            return Response({
                'error': 'Team not found.'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'])
    def standings(self, request, league_pk=None, pk=None):
        season = self.get_object()
        standings = season.standings(request=request)
        
        return Response(standings)
    
    @action(detail=True, methods=['get'])
    def team_performance(self, request, league_pk=None, pk=None):
        """Get detailed performance metrics for teams in a season"""
        try:
            season = self.get_object()
        except Season.DoesNotExist:
            return Response(
                {"detail": "Season not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Use the team performance service to get the data
        from .services import TeamPerformanceService
        service = TeamPerformanceService(season, request)
        team_performance = service.get_team_performance()
        
        return Response(team_performance)
    
    @action(detail=False, methods=['get'])
    def comparison(self, request, league_pk=None):
        """Compare multiple seasons in the same league"""
        league = get_object_or_404(League, pk=league_pk)
        seasons_ids = request.query_params.get('seasons', '').split(',')
        
        from .services import SeasonComparisonService
        service = SeasonComparisonService(league)
        
        # Only pass seasons_ids if they're valid
        if seasons_ids and seasons_ids[0]:
            comparison_data = service.get_comparison_data(seasons_ids)
        else:
            comparison_data = service.get_comparison_data()
            
        return Response(comparison_data)
    
    @action(detail=True, methods=['get'])
    def games(self, request, league_pk=None, pk=None):
        """Get all games in a season with filtering options"""
        season = self.get_object()
        
        from .services import SeasonGamesService
        from games.serializers import GameSerializer
          # Create filters from query parameters
        filters = {
            'status': request.query_params.get('status'),
            'team_id': request.query_params.get('team'),
            'date': request.query_params.get('date')
        }
        
        # Get filtered games using the service
        service = SeasonGamesService(season)
        games = service.get_games(filters)
        serializer = GameSerializer(games, many=True, context={'request': request})
  
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def teams(self, request, league_pk=None, pk=None):
        """Get all teams in a season with extended information and standings order"""
        season = self.get_object()
        
        from .services import SeasonTeamsService
        from teams.serializers import TeamSerializer
        
        # Get sort parameter (default to True if not specified)
        sort_by_standings = request.query_params.get('sort_by_standings', 'true').lower() != 'false'
        
        # Get teams with stats using the service
        # This already uses season.standings() internally when sort_by_standings is True
        service = SeasonTeamsService(season, request)
        teams, team_stats = service.get_teams_with_stats(sort_by_standings=sort_by_standings)
        
        # Serialize the team data and add the stats
        serialized_teams = []
        for team in teams:
            team_data = TeamSerializer(team, context={'request': request}).data
            
            # Add the stats information to the serialized data
            # team_stats already contains all the standings data including rank
            if team.id in team_stats:
                team_data.update(team_stats[team.id])
                
            serialized_teams.append(team_data)
        
        return Response(serialized_teams)
    
    @action(detail=True, methods=['get'])
    def season_leaders(self, request, league_pk=None, pk=None):
        """Get the top players from each team for each leader category in a season"""
        try:
            season = self.get_object()
            
            from .services import SeasonLeaderService
            service = SeasonLeaderService(season_id=season.id, request=request)
            data = service.get_season_leaders()
            
            return Response(data)
        except Exception as e:
            return Response(
                {"error": f"Failed to get season leaders: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def team_form(self, request, league_pk=None, pk=None):
        """Get the recent form for teams in a season"""
        season = self.get_object()
        
        from .services import TeamFormService
        service = TeamFormService(season)
        team_form_data = service.get_team_form()
        
        return Response({
            'teams': team_form_data[0],
            'form': team_form_data[1]
        })

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum, Avg, F, Q

from .models import Tournament
from .serializers import (
    TournamentSerializer, 
    TournamentWriteSerializer, 
    TeamStandingsSerializer,
    TournamentStatisticsSerializer
)
from teams.models import Team
from sports.models import Sport


class TournamentPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


class TournamentViewSet(viewsets.ModelViewSet):
    queryset = Tournament.objects.select_related('sport').prefetch_related('teams', 'games')
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = TournamentPagination

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return TournamentWriteSerializer
        return TournamentSerializer
    
    @action(detail=True, methods=["get"])
    def standings(self, request, pk=None):
        """Get tournament standings"""
        tournament = self.get_object()
        standings = tournament.standings(request=request)
        
        return Response(standings)
    
    @action(detail=True, methods=["get"])
    def statistics(self, request, pk=None):
        """Get comprehensive tournament statistics"""
        tournament = self.get_object()
        
        from .services.tournament_statistics_service import TournamentStatisticsService
        
        service = TournamentStatisticsService(tournament, request)
        stats = service.get_statistics()
        
        return Response(stats)
    
    @action(detail=True, methods=["get"])
    def comprehensive_stats(self, request, pk=None):
        """Get detailed comprehensive statistics for the tournament"""
        tournament = self.get_object()
        
        from .services.tournament_statistics_service import TournamentStatisticsService
        
        service = TournamentStatisticsService(tournament, request)
        stats = service.get_comprehensive_stats()
        
        return Response(stats)
    
    @action(detail=True, methods=["get"])
    def team_form(self, request, pk=None):
        """Get recent form for teams in the tournament"""
        tournament = self.get_object()
        
        from .services.tournament_statistics_service import TournamentStatisticsService
        
        service = TournamentStatisticsService(tournament, request)
        team_form_data = service.get_team_form()
        
        return Response(team_form_data)
    
    @action(detail=True, methods=["get"])
    def leaders(self, request, pk=None):
        """Get the top players for each leader category in the tournament"""
        try:
            tournament = self.get_object()
            
            from .services.tournament_leader_service import TournamentLeaderService
            
            service = TournamentLeaderService(tournament_id=tournament.id, request=request)
            data = service.get_tournament_leaders()
            
            return Response(data)
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=["get"])
    def games(self, request, pk=None):
        """Get all games in a tournament with filtering options"""
        tournament = self.get_object()
        
        from games.models import Game
        from games.serializers import GameSerializer
        
        # Start with games for this tournament
        games = Game.objects.filter(tournament=tournament).select_related(
            'home_team', 'away_team', 'sport'
        ).order_by('date', 'time')
        
        # Apply filters from query parameters
        status_filter = request.query_params.get('status')
        if status_filter:
            games = games.filter(status=status_filter)
        
        team_filter = request.query_params.get('team')
        if team_filter:
            games = games.filter(
                Q(home_team_id=team_filter) | Q(away_team_id=team_filter)
            )
        
        date_filter = request.query_params.get('date')
        if date_filter:
            games = games.filter(date=date_filter)
        
        serializer = GameSerializer(games, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=["post"])
    def add_team(self, request, pk=None):
        """Add a team to the tournament"""
        tournament = self.get_object()
        team_id = request.data.get("team_id")
        
        if not team_id:
            return Response(
                {"detail": "team_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            team = Team.objects.get(id=team_id)
            tournament.add_team(team)
            return Response(
                {"detail": f"Team {team.name} added to tournament"},
                status=status.HTTP_200_OK
            )
        except Team.DoesNotExist:
            return Response(
                {"detail": "Team not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except ValidationError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=["post"])
    def remove_team(self, request, pk=None):
        """Remove a team from the tournament"""
        tournament = self.get_object()
        team_id = request.data.get("team_id")
        
        if not team_id:
            return Response(
                {"detail": "team_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            team = Team.objects.get(id=team_id)
            tournament.remove_team(team)
            return Response(
                {"detail": f"Team {team.name} removed from tournament"},
                status=status.HTTP_200_OK
            )
        except Team.DoesNotExist:
            return Response(
                {"detail": "Team not found"},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=["post"])
    def manage(self, request, pk=None):
        """Manage tournament state (start, complete, pause, cancel)"""
        tournament = self.get_object()
        action_type = request.data.get("action")
        
        if not action_type:
            return Response(
                {"detail": "action is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from .services.tournament_management_service import TournamentManagementService
            
            service = TournamentManagementService(tournament)
            result = service.manage_tournament(action_type)
            
            return Response(result, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=["get"])
    def team_statistics(self, request, pk=None):
        """Get statistics for a specific team in the tournament"""
        tournament = self.get_object()
        team_id = request.query_params.get("team_id")
        
        if not team_id:
            return Response(
                {"detail": "team_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            team = Team.objects.get(id=team_id)
            
            from .services.tournament_team_service import TournamentTeamService
            
            service = TournamentTeamService(tournament, team, request)
            stats = service.get_team_statistics()
            
            return Response(stats)
        except Team.DoesNotExist:
            return Response(
                {"detail": "Team not found"},
                status=status.HTTP_404_NOT_FOUND
            )


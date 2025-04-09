from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import League, Season
from .serializers import LeagueSerializer, LeagueWriteSerializer, SeasonSerializer, TeamStandingsSerializer
from django.shortcuts import get_object_or_404

class LeagueViewSet(viewsets.ModelViewSet):
    queryset = League.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return LeagueWriteSerializer
        return LeagueSerializer

    @action(detail=True, methods=['post'])
    def add_team(self, request, pk=None):
        league = self.get_object()
        team_id = request.data.get('team_id')
        
        if not team_id:
            return Response({'error': 'team_id required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if league.teams.filter(id=team_id).exists():
            return Response({'status': 'Team already in league'})
            
        team = Team.objects.get(id=team_id)
        if team.sport != league.sport:
            return Response({'error': 'Team sport mismatch'}, status=400)
            
        league.teams.add(team)
        return Response({'status': 'Team added'})

    @action(detail=True, methods=['post'])
    def remove_team(self, request, pk=None):
        league = self.get_object()
        team_id = request.data.get('team_id')
        
        if not team_id:
            return Response({'error': 'team_id required'}, status=400)
            
        league.teams.remove(team_id)
        return Response({'status': 'Team removed'})
    
class SeasonViewSet(viewsets.ModelViewSet):
    serializer_class = SeasonSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return Season.objects.filter(league_id=self.kwargs['league_pk'])

    def perform_create(self, serializer):
        league = get_object_or_404(League, pk=self.kwargs['league_pk'])
        serializer.save(league=league)
    
    @action(detail=True, methods=['get'])
    def standings(self, request, league_pk=None, pk=None):
        season = self.get_object()
        raw_standings = season.standings()
        
        standings_data = {item['team_id']: item for item in raw_standings}
        
        teams = season.league.teams.all()
        
        serializer = TeamStandingsSerializer(
            teams,
            many=True,
            context={
                'request': request,
                'standings_data': standings_data
            }
        )
        
        # Sort by standings criteria
        sorted_data = sorted(
            serializer.data,
            key=lambda x: (
                -x['standings'].get('points', 0),
                -x['standings'].get('win_percentage', 0)
            )
        )
        
        return Response(sorted_data)
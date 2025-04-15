from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import League, Season
from .serializers import LeagueSerializer, LeagueWriteSerializer, SeasonSerializer, TeamStandingsSerializer
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError

class LeagueViewSet(viewsets.ModelViewSet):
    queryset = League.objects.all()
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
    
class SeasonViewSet(viewsets.ModelViewSet):
    serializer_class = SeasonSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return Season.objects.filter(league_id=self.kwargs['league_pk'])

    def perform_create(self, serializer):
        league = get_object_or_404(League, pk=self.kwargs['league_pk'])
        serializer.save(league=league)
        
    
    @action(detail=True, methods=["post"])
    def manage(self, request, pk=None, **kwargs):
        season = self.get_object()
        action_type = request.data.get("action")

        try:
            if action_type == "start":
                season.start_season()
                return Response({"detail": "Season started."}, status=status.HTTP_200_OK)

            elif action_type == "complete":
                season.complete_season()
                return Response({"detail": "Season completed."}, status=status.HTTP_200_OK)

            elif action_type == "pause":
                season.pause_season()
                return Response({"detail": "Season paused."}, status=status.HTTP_200_OK)

            elif action_type == "cancel":
                season.cancel_season()
                return Response({"detail": "Season canceled."}, status=status.HTTP_200_OK)

            else:
                return Response({"detail": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)

        except ValidationError as e:
            return Response({"detail": e.message}, status=status.HTTP_400_BAD_REQUEST)
        
    @action(detail=True, methods=['post'])
    def add_team(self, request, pk=None):
        season = self.get_object()
        team_id = request.data.get('team_id')
        
        if not team_id:
            return Response({'error': 'team_id required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if season.teams.filter(id=team_id).exists():
            return Response({'status': 'Team already in season'})
            
        team = Team.objects.get(id=team_id)
        if team.sport != season.sport:
            return Response({'error': 'Team sport mismatch'}, status=400)
            
        season.teams.add(team)
        return Response({'status': 'Team added'})

    @action(detail=True, methods=['post'])
    def remove_team(self, request, pk=None):
        season = self.get_object()
        team_id = request.data.get('team_id')
        
        if not team_id:
            return Response({'error': 'team_id required'}, status=400)
            
        season.teams.remove(team_id)
        return Response({'status': 'Team removed'})
    
    @action(detail=True, methods=['get'])
    def standings(self, request, league_pk=None, pk=None):
        season = self.get_object()
        raw_standings = season.standings()
        
        standings_data = {item['team_id']: item for item in raw_standings}
        
        teams = season.teams.all()
        
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
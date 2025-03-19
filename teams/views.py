from rest_framework.viewsets import ModelViewSet, GenericViewSet
from rest_framework.mixins import CreateModelMixin
from .serializers import SportsTeamSerializer, PlayerSerializer, CoachSerializer, TeamSerializer
from rest_framework.response import Response
from .models import Team
from .models import Player, Coach
from rest_framework.permissions import IsAuthenticated
from sports_management.permissions import IsAdminUser, IsAdminOrCoachUser
from collections import defaultdict

class TeamViewSet(ModelViewSet):
    queryset = Team.objects.all()
    lookup_field = "slug"
    
    def get_serializer_class(self):
        if self.action == "list":
            return SportsTeamSerializer  # Grouped output for the list
        return TeamSerializer  # Default detailed output for a single team
    
    def list(self, request):
        grouped_teams = defaultdict(list)
        
        for team in Team.objects.select_related("sport").all():
            grouped_teams[team.sport.name].append(team)

        formatted_data = [{"sport": sport, "teams": teams} for sport, teams in grouped_teams.items()]
        
        serializer = SportsTeamSerializer(formatted_data, many=True, context={"request": request})
        return Response(serializer.data)
    
class PlayerViews(ModelViewSet):
    queryset = Player.objects.all()
    serializer_class = PlayerSerializer

class CreatePlayerView(CreateModelMixin, GenericViewSet):   
    permission_classes = [IsAuthenticated, IsAdminOrCoachUser]
    queryset = Player.objects.all()
    serializer_class = PlayerSerializer
    
class CoachViews(ModelViewSet):
    queryset = Coach.objects.all()
    serializer_class = CoachSerializer

class CreateCoachView(CreateModelMixin, GenericViewSet):
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Coach.objects.all()
    serializer_class = CoachSerializer
    
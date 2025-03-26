from rest_framework.viewsets import ModelViewSet
from .serializers import PlayerInfoSerializer, CoachSerializer, TeamSerializer
from rest_framework.response import Response
from .models import Team
from .models import Player, Coach
from rest_framework.permissions import IsAuthenticated
from sports_management.permissions import IsAdminUser, IsAdminOrCoachUser
from collections import defaultdict

class TeamViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Team.objects.all()
    serializer_class = TeamSerializer
    lookup_field = "slug"
    
class PlayerViews(ModelViewSet):
    permission_classes = [IsAdminOrCoachUser]
    queryset = Player.objects.all()
    serializer_class = PlayerInfoSerializer
    lookup_field = "slug"
    
class CoachViews(ModelViewSet):
    permission_classes = [IsAdminUser]
    queryset = Coach.objects.all()
    serializer_class = CoachSerializer

    
    
from rest_framework.viewsets import ModelViewSet, GenericViewSet
from rest_framework.mixins import CreateModelMixin
from .serializers import TeamSerializer, PlayerSerializer, CoachSerializer
from .models import Team
from .models import Player, Coach
from rest_framework.permissions import IsAuthenticated
from sports_management.permissions import IsAdminUser, IsAdminOrCoachUser

class TeamViewSet(ModelViewSet):
    queryset = Team.objects.all()
    serializer_class = TeamSerializer

class CreatePlayerView(CreateModelMixin, GenericViewSet):
    permission_classes = [IsAuthenticated, IsAdminOrCoachUser]
    queryset = Player.objects.all()
    serializer_class = PlayerSerializer

class CreateCoachView(CreateModelMixin, GenericViewSet):
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Coach.objects.all()
    serializer_class = CoachSerializer
    
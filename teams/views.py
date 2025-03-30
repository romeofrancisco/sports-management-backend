from rest_framework.viewsets import ModelViewSet, GenericViewSet
from rest_framework.mixins import CreateModelMixin
from .serializers import PlayerInfoSerializer, CoachSerializer, TeamSerializer
from .models import Team
from .models import Player, Coach
from rest_framework.permissions import IsAuthenticated
from sports_management.permissions import IsAdminUser, IsAdminOrCoachUser
from django.db.models import Count, Case, When, IntegerField, Q, F


class TeamViewSet(ModelViewSet):
    queryset = Team.objects.all()
    lookup_field = "slug"
    serializer_class = TeamSerializer


class PlayerViews(ModelViewSet):
    queryset = Player.objects.all()
    serializer_class = PlayerInfoSerializer
    lookup_field = "slug"


class CoachViews(ModelViewSet):
    queryset = Coach.objects.all()
    serializer_class = CoachSerializer


class CreateCoachView(CreateModelMixin, GenericViewSet):
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Coach.objects.all()
    serializer_class = CoachSerializer

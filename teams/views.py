from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from .serializers import PlayerInfoSerializer, CoachInfoSerializer, TeamSerializer
from .models import Player, Coach, Team
from sports.models import Sport
from rest_framework.permissions import IsAuthenticated
from sports_management.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import F
from .filters import CoachFilter, PlayerFilter
from rest_framework.pagination import PageNumberPagination


class PlayerPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class TeamViewSet(ModelViewSet):
    queryset = Team.objects.all()
    lookup_field = "slug"
    serializer_class = TeamSerializer
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["name"]
    filterset_fields = ["sport", "division"]


class SportTeamsViewSet(ReadOnlyModelViewSet):
    serializer_class = TeamSerializer
    lookup_field = "pk"

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
    pagination_class = PlayerPagination

    def get_queryset(self):
        return Player.objects.select_related("user").annotate(
            first_name=F("user__first_name"),
            last_name=F("user__last_name"),
            sex=F("user__sex"),
        ).order_by('user__first_name')


class CoachViews(ModelViewSet):
    queryset = Coach.objects.all().prefetch_related("team_set")
    serializer_class = CoachInfoSerializer
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["first_name", "last_name"]
    filterset_class = CoachFilter
    
    def get_queryset(self):
        return Coach.objects.select_related("user").annotate(
            first_name=F("user__first_name"),
            last_name=F("user__last_name"),
            sex=F("user__sex"),
        )

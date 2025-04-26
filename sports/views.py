from rest_framework.viewsets import ModelViewSet
from .models import Sport, Position, SportStatType, Formula
from .serializers import (
    SportSerializer,
    PositionSerializer,
    SportStatTypeSerializer,
    FormulaSerializer,
)
from django_filters.rest_framework import DjangoFilterBackend
from .filters import SportStatTypeFilter, SportPositionFilter
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from rest_framework.filters import SearchFilter


class SportsViewSet(ModelViewSet):
    queryset = Sport.objects.all()
    serializer_class = SportSerializer
    lookup_field = "slug"


class SportStatTypeViewSet(ModelViewSet):
    queryset = SportStatType.objects.select_related("sport").all()
    serializer_class = SportStatTypeSerializer
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ["name"]
    filterset_class = SportStatTypeFilter


class FormulaViewSet(ModelViewSet):
    queryset = Formula.objects.all().prefetch_related(
        "components", "components__stat_type", "sport"
    )
    serializer_class = FormulaSerializer
    filter_backends = [SearchFilter]
    search_fields = ["name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        sport_slug = self.request.query_params.get("sport")

        if sport_slug:
            sport = get_object_or_404(Sport, slug=sport_slug)
            queryset = queryset.filter(sport=sport)

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=201, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


class PositionViewSet(ModelViewSet):
    serializer_class = PositionSerializer
    queryset = Position.objects.select_related("sport").all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = SportPositionFilter

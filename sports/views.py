from rest_framework.viewsets import ModelViewSet
from .models import Sport, Position, SportStatType
from .serializers import SportSerializer, PositionSerializer, SportStatTypeSerializer
from django_filters.rest_framework import DjangoFilterBackend

class SportsViewSet(ModelViewSet):
    queryset = Sport.objects.all()
    serializer_class = SportSerializer
    lookup_field = "slug"

class SportStatTypeViewSet(ModelViewSet):
    queryset = SportStatType.objects.all()
    serializer_class = SportStatTypeSerializer
    filterset_fields = ['sport']

class PositionViewSet(ModelViewSet):
    serializer_class = PositionSerializer
    queryset = Position.objects.select_related('sport').all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['sport']

    


from rest_framework.viewsets import ModelViewSet
from .models import Sport, Position, SportStatType
from .serializers import SportSerializer, PositionSerializer, SportStatTypeSerializer

class SportsViewSet(ModelViewSet):
    queryset = Sport.objects.all()
    serializer_class = SportSerializer
    lookup_field = "slug"

class SportStatTypeViewSet(ModelViewSet):
    queryset = SportStatType.objects.all()
    serializer_class = SportStatTypeSerializer
    filterset_fields = ['sport']

class PositionViewSet(ModelViewSet):
    queryset = Position.objects.all()
    serializer_class = PositionSerializer

    


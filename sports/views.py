from rest_framework.viewsets import ModelViewSet
from .models import Sport, Position
from .serializers import SportSerializer, PositionSerializer

class SportsViewSet(ModelViewSet):
    queryset = Sport.objects.all()
    serializer_class = SportSerializer

class PositionViewSet(ModelViewSet):
    queryset = Position.objects.all()
    serializer_class = PositionSerializer
    


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
    serializer_class = PositionSerializer
    
    def get_queryset(self):
        queryset = Position.objects.all()
        sport = self.request.query_params.get('sport')
        
        if sport:
            queryset = queryset.filter(
                sport__slug__iexact=sport
            ).select_related('sport')  # Optimizes related sport data fetching
        return queryset

    


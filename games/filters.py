from django_filters import rest_framework as filters
from .models import Game

class GameFilter(filters.FilterSet):
    start_date = filters.DateFilter(field_name="date", lookup_expr='gte')
    end_date = filters.DateFilter(field_name="date", lookup_expr='lte')
    
    class Meta:
        model = Game
        fields = {
            'status': ['exact'],
            'sport': ['exact'],
            'league': ['exact'],
            'season': ['exact'],
            'type': ['exact'],
            'date': ['exact', 'lt', 'gt'],
        }
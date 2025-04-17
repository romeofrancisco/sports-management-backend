from django_filters import rest_framework as filters
from .models import Game
from django.db.models import Q

class GameFilter(filters.FilterSet):
    start_date = filters.DateFilter(field_name="date", lookup_expr='gte')
    end_date = filters.DateFilter(field_name="date", lookup_expr='lte')
    team_name = filters.CharFilter(method='filter_by_team_name', label="Search team name")
    
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
    
    def filter_by_team_name(self, queryset, name, value):
        return queryset.filter(
            Q(home_team__name__icontains=value) |
            Q(away_team__name__icontains=value)
        )
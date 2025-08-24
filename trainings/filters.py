from django_filters import rest_framework as filters
from .models import TrainingSession, PlayerTraining
from django.db.models import Q

class TrainingSessionFilter(filters.FilterSet):
    start_date = filters.DateFilter(field_name="date", lookup_expr='gte')
    end_date = filters.DateFilter(field_name="date", lookup_expr='lte')
    search = filters.CharFilter(method='filter_by_search', label="Search by title, description or location")
    team = filters.NumberFilter(field_name="team", method='filter_by_team')
    status = filters.CharFilter(method='filter_by_status', label="Filter by session status")
    
    class Meta:
        model = TrainingSession
        fields = {
            'categories': ['exact'],
            'date': ['exact', 'lt', 'gt'],
        }
    
    def filter_by_team(self, queryset, name, value):
        """Allow filtering by team, handling both exact matches and empty values"""
        if value is None or value == '':
            return queryset
        return queryset.filter(team_id=value)
    
    def filter_by_search(self, queryset, name, value):
        return queryset.filter(
            Q(title__icontains=value) |
            Q(description__icontains=value) |
            Q(location__icontains=value)
        )
    
    def filter_by_status(self, queryset, name, value):
        """Filter by session status based on date and time"""
        if not value:
            return queryset
            
        from django.utils import timezone
        now = timezone.now()
        
        if value == 'upcoming':
            # Include future dates AND today's sessions that haven't started yet
            return queryset.filter(
                Q(date__gt=now.date()) |
                Q(date=now.date(), start_time__gt=now.time())
            )
        elif value == 'ongoing':
            return queryset.filter(
                date=now.date(),
                start_time__lte=now.time(),
                end_time__gte=now.time()
            )
        elif value == 'completed':
            return queryset.filter(
                Q(date__lt=now.date()) |
                Q(date=now.date(), end_time__lt=now.time())
            )
        
        return queryset

class PlayerTrainingFilter(filters.FilterSet):
    start_date = filters.DateFilter(field_name="session__date", lookup_expr='gte')
    end_date = filters.DateFilter(field_name="session__date", lookup_expr='lte')
    team = filters.CharFilter(field_name="session__team__slug", lookup_expr="exact")
    player_name = filters.CharFilter(method='filter_by_player_name', label="Search player name")

    class Meta:
        model = PlayerTraining
        fields = {
            'player': ['exact'],
            'session': ['exact'],
            'attendance_status': ['exact'],
            'session__date': ['exact', 'lt', 'gt'],
        }

    def filter_by_player_name(self, queryset, name, value):
        return queryset.filter(
            Q(player__user__first_name__icontains=value) |
            Q(player__user__last_name__icontains=value)
        )

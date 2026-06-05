import django_filters
from .models import Player, Coach
from users.models import User
from django.db.models import Q

class PlayerFilter(django_filters.FilterSet):
    sex = django_filters.ChoiceFilter(field_name="user__sex", choices=User.Sex.choices)
    is_active = django_filters.BooleanFilter(field_name="user__is_active")
    team = django_filters.CharFilter(method='filter_team')
    year_level = django_filters.CharFilter(field_name="academic_info__year_level", lookup_expr="icontains")
    course = django_filters.CharFilter(field_name="academic_info__course", lookup_expr="icontains")
    section = django_filters.CharFilter(field_name="academic_info__section", lookup_expr="icontains")

    def filter_team(self, queryset, name, value):
        """
        Filter by team using either slug or ID
        """
        if not value:
            return queryset

        # Try to parse the value as an integer (team ID)
        try:
            team_id = int(value)
            team_filter = Q(team__id=team_id)
        except ValueError:
            # If not an integer, treat as slug
            team_filter = Q(team__slug=value)

        return queryset.filter(team_filter)

    class Meta:
        model = Player
        fields = ["sport", "year_level", "course", "sex", "team", "is_active"]

class CoachFilter(django_filters.FilterSet):
    sex = django_filters.ChoiceFilter(field_name="user__sex", choices=User.Sex.choices)
    is_active = django_filters.BooleanFilter(field_name="user__is_active")
    sport = django_filters.NumberFilter(field_name="sports", lookup_expr="exact")
    search = django_filters.CharFilter(method='filter_search')

    def filter_search(self, queryset, name, value):
        """
        Search by coach's first name, last name, or email
        """
        if not value:
            return queryset
        
        return queryset.filter(
            Q(user__first_name__icontains=value) |
            Q(user__last_name__icontains=value) |
            Q(user__email__icontains=value)
        )

    class Meta:
        model = Coach
        fields = ['sex', 'sport', 'search', 'is_active']
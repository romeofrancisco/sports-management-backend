import django_filters
from .models import Player, Coach
from users.models import User
from django.db.models import Q

class PlayerFilter(django_filters.FilterSet):
    sex = django_filters.ChoiceFilter(field_name="user__sex", choices=User.Sex.choices)
    team = django_filters.CharFilter(method='filter_team')

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
        fields = ["sport", "year_level", "course", "sex", "team"]

class CoachFilter(django_filters.FilterSet):
    sex = django_filters.ChoiceFilter(field_name="user__sex", choices=User.Sex.choices)

    class Meta:
        model = Coach
        fields = ['sex']
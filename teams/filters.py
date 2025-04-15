import django_filters
from .models import Player
from users.models import User

class PlayerFilter(django_filters.FilterSet):
    sex = django_filters.ChoiceFilter(field_name="user__sex", choices=User.Sex.choices)

    class Meta:
        model = Player
        fields = ["sport", "year_level", "course", "sex"]
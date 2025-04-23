import django_filters
from .models import Position, SportStatType, Formula


class SportStatTypeFilter(django_filters.FilterSet):
    sport = django_filters.CharFilter(field_name="sport__slug", lookup_expr="iexact")
    is_record = django_filters.BooleanFilter()

    class Meta:
        model = SportStatType
        fields = ["sport", "is_record"]


class SportPositionFilter(django_filters.FilterSet):
    sport = django_filters.CharFilter(field_name="sport__slug", lookup_expr="iexact")

    class Meta:
        model = Position
        fields = ["sport"]
